"""
Database History & Multi-User Manager (Nutrisi Cerdas v4.0)
Mendukung Dual-Backend otomatis:
1. Supabase PostgreSQL (via pg8000 SSL) jika DATABASE_URL dikonfigurasi — permanen lintas restart & perangkat.
2. SQLite lokal (tkpi_nutrition.db) sebagai fallback otomatis & untuk uji lokal.
"""

import hashlib
import hmac
import math
import os
import secrets
import sqlite3
import ssl
import threading
import time
import urllib.parse
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from food_guardrails import (
    FoodGuardrailRejected,
    MAX_DAILY_KCAL_PER_USER,
    MAX_DAILY_MEALS_PER_USER,
    MAX_SINGLE_DISH_KCAL,
    validate_display_name,
    validate_food_candidate,
    validate_food_text_query,
    validate_nutrition_sanity,
)

try:
    import pg8000.dbapi as pg_dbapi
    _HAS_PG8000 = True
except ImportError:
    pg_dbapi = None
    _HAS_PG8000 = False

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")
_MODULE_MTIME = round(os.path.getmtime(__file__), 6) if os.path.exists(__file__) else 0.0

# Mode Rilis Open Beta: QRIS ditutup sementara, teman terdaftar mendapat 5x scan foto AI/hari
OPEN_BETA_MODE = True
BETA_DAILY_SCAN_LIMIT = 5
GUEST_DAILY_SCAN_LIMIT = 3
DEFAULT_TIMEZONE_OFFSET = 8  # WITA (Tanah Grogot / Kaltim)
SESSION_TOKEN_TTL_SECONDS = 30 * 86400  # 30 hari masa berlaku token tautan sesi ?u=&s=

ADMIN_IDENTIFIERS = {
    "nabillah",
    "muhammadnabillah0coder@gmail.com",
    "pkm tanah grogot",
    "admin"
}

TABLES_WITH_ID = {
    "users",
    "meal_logs",
    "water_logs",
    "weight_logs",
    "custom_foods",
    "pending_foods",
    "food_catalog_additions",
    "payment_orders",
    "pro_vouchers",
}

SCHEMA_VERSION = "v4.6"
GUEST_PREFIX = "guest_"
VALID_FASTING_MODES = (
    "Normal",
    "Puasa Sunnah / Ramadan",
    "Intermittent Fasting 16:8",
)
_INITIALIZED_BACKENDS: set[str] = set()


def is_guest_user_id(user_id: str) -> bool:
    """Mengembalikan True bila user_id adalah sesi tamu anonim (baik legacy Tamu (Demo) maupun guest_<hex>)."""
    raw = str(user_id or "").strip().lower()
    return (not raw) or (raw == "tamu (demo)") or raw.startswith(GUEST_PREFIX)


def create_guest_session_id() -> str:
    """Membuat ID sesi tamu terisolasi per browser agar catatan antar pengunjung tidak bercampur."""
    return f"{GUEST_PREFIX}{secrets.token_hex(6)}"


def compute_water_target_glasses(weight_kg: float = 65.0, focus_goal: str = "Diet Sehat") -> int:
    """Menghitung target air minum harian adaptif (~33 ml/kg BB + bonus Ibu Hamil, min 8 gelas / 2000ml)."""
    try:
        w = float(weight_kg or 65.0)
    except (TypeError, ValueError):
        w = 65.0
    if not math.isfinite(w) or w <= 0:
        w = 65.0
    bonus_ml = 350.0 if "hamil" in str(focus_goal or "").lower() else 0.0
    ml = (w * 33.0) + bonus_ml
    return max(8, min(14, int(round(ml / 250.0))))
_LAST_CLOUD_ERROR: str = ""
_PG_POOL_LOCK = threading.Lock()
_PG_POOL: dict[str, deque] = {}
_PG_POOL_IDLE_TTL = 75.0
_PG_POOL_MAX_PER_KEY = 4


class _DictRow(dict):
    """Objek baris kompatibel sqlite3.Row (mendukung akses indeks angka maupun nama kolom)."""

    def __init__(self, columns, values):
        norm_vals = []
        for v in values:
            if isinstance(v, datetime):
                norm_vals.append(v.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(v, Decimal):
                norm_vals.append(float(v))
            else:
                norm_vals.append(v)
        super().__init__(zip(columns, norm_vals))
        self._values = norm_vals

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _translate_qmark_to_pg(sql: str) -> str:
    """Mengubah placeholder '?' (SQLite) menjadi '%s' (pg8000) dengan aman di luar literal string."""
    out = []
    in_quote = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            if in_quote and i + 1 < n and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_quote = not in_quote
        elif ch == "?" and not in_quote:
            out.append("%s")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _inject_returning_id(pg_sql: str) -> tuple[str, bool]:
    """Menambahkan RETURNING id pada INSERT PostgreSQL agar lastrowid bekerja identik dengan SQLite."""
    stripped = pg_sql.strip().rstrip(";")
    upper = stripped.upper()
    if not upper.startswith("INSERT INTO "):
        return pg_sql, False
    after_into = stripped[12:].lstrip()
    table_name = after_into.split("(")[0].split()[0].strip().strip('"').lower()
    if table_name not in TABLES_WITH_ID or "RETURNING" in upper:
        return pg_sql, False
    return f"{stripped} RETURNING id", True


def _is_transport_error(exc: Exception) -> bool:
    if isinstance(exc, OSError):
        return True
    msg = f"{type(exc).__name__} {exc}".lower()
    return any(tok in msg for tok in ("interfaceerror", "closed", "broken", "eof", "reset", "timeout", "connection"))


class _UnifiedCursor:
    """Wrapper kursor seragam untuk SQLite dan PostgreSQL (pg8000) dengan auto-retry pool."""

    def __init__(self, raw_cur, conn: "_UnifiedConnection"):
        self._raw = raw_cur
        self._conn = conn
        self.backend = conn.backend
        self.lastrowid = None

    def _exec_pg_once(self, pg_sql: str, added_returning: bool, params):
        self._raw.execute(pg_sql, tuple(params) if params is not None else ())
        if added_returning:
            row = self._raw.fetchone()
            self.lastrowid = row[0] if row else None
        else:
            self.lastrowid = getattr(self._raw, "lastrowid", None)

    def execute(self, sql: str, params=()):
        if self.backend == "sqlite":
            self._raw.execute(sql, params)
            self.lastrowid = getattr(self._raw, "lastrowid", None)
            return self

        pg_sql = _translate_qmark_to_pg(sql)
        pg_sql, added_returning = _inject_returning_id(pg_sql)
        try:
            self._exec_pg_once(pg_sql, added_returning, params)
        except Exception as exc:
            if self._conn._from_pool and self._conn._queries_run == 0 and self._conn._uri and _is_transport_error(exc):
                self._conn._refresh_raw_pg()
                self._raw = self._conn._raw.cursor()
                self._exec_pg_once(pg_sql, added_returning, params)
            else:
                self._conn._broken = True
                raise
        self._conn._queries_run += 1
        return self

    def _wrap_row(self, raw_row):
        if raw_row is None:
            return None
        if self.backend == "sqlite":
            return raw_row
        cols = [d[0] for d in (self._raw.description or [])]
        return _DictRow(cols, raw_row)

    def fetchone(self):
        return self._wrap_row(self._raw.fetchone())

    def fetchall(self):
        rows = self._raw.fetchall()
        if self.backend == "sqlite":
            return rows
        cols = [d[0] for d in (self._raw.description or [])]
        return [_DictRow(cols, r) for r in rows]


class _UnifiedConnection:
    """Wrapper koneksi seragam dengan backend SQLite atau PostgreSQL."""

    def __init__(self, raw_conn, backend: str, uri: str = "", from_pool: bool = False):
        self._raw = raw_conn
        self.backend = backend
        self._uri = uri
        self._from_pool = from_pool
        self._queries_run = 0
        self._broken = False

    def _refresh_raw_pg(self):
        try:
            self._raw.close()
        except Exception:
            pass
        self._raw = _open_pg_raw(self._uri)
        self._from_pool = False
        self._queries_run = 0
        self._broken = False

    def cursor(self):
        return _UnifiedCursor(self._raw.cursor(), self)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        try:
            self._raw.rollback()
        except Exception:
            self._broken = True

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass


def get_database_url() -> str:
    """Mengambil DATABASE_URL dari environment variable atau Streamlit Secrets secara aman."""
    env_url = (os.environ.get("DATABASE_URL") or "").strip().strip('"').strip("'")
    if not env_url:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "DATABASE_URL" in st.secrets:
                    env_url = str(st.secrets["DATABASE_URL"]).strip()
                elif "connections" in st.secrets and "postgresql" in st.secrets["connections"]:
                    pg_sec = st.secrets["connections"]["postgresql"]
                    if "url" in pg_sec:
                        env_url = str(pg_sec["url"]).strip()
        except Exception:
            pass

    if env_url.startswith("postgres://") or env_url.startswith("postgresql://"):
        return env_url
    return ""


def parse_database_url(uri: str) -> dict:
    """Mem-parsing URI PostgreSQL/Supabase secara aman menjadi parameter koneksi pg8000."""
    clean = (uri or "").strip()
    if not (clean.startswith("postgres://") or clean.startswith("postgresql://")):
        raise ValueError("DATABASE_URL harus diawali postgresql:// atau postgres://")

    parsed = urllib.parse.urlparse(clean)
    if not parsed.hostname:
        raise ValueError("Host database tidak ditemukan di dalam DATABASE_URL.")

    query_params = urllib.parse.parse_qs(parsed.query)
    sslmode = (query_params.get("sslmode", [""])[0] or "").lower()
    is_local_host = parsed.hostname in {"localhost", "127.0.0.1"}
    is_supabase_host = parsed.hostname.endswith(".supabase.com") or parsed.hostname.endswith(".supabase.co")
    use_ssl = False if (sslmode == "disable" or (is_local_host and sslmode != "require")) else True

    if sslmode in {"verify-ca", "verify-full"}:
        ssl_verify = True
    elif sslmode in {"no-verify", "require"} or (not sslmode and is_supabase_host):
        # Standar libpq sslmode=require / pooler Supabase memakai TLS tanpa verifikasi CA internal
        ssl_verify = False
    else:
        ssl_verify = True

    return {
        "user": urllib.parse.unquote(parsed.username or "postgres"),
        "password": urllib.parse.unquote(parsed.password or ""),
        "host": parsed.hostname,
        "port": int(parsed.port or 5432),
        "database": (parsed.path or "/postgres").lstrip("/") or "postgres",
        "use_ssl": use_ssl,
        "ssl_verify": ssl_verify,
    }


def _open_pg_raw(uri: str):
    if not _HAS_PG8000:
        raise RuntimeError("Driver pg8000 belum terpasang di lingkungan Python.")
    cfg = parse_database_url(uri)
    ssl_ctx = None
    if cfg["use_ssl"]:
        ssl_ctx = ssl.create_default_context()
        if not cfg["ssl_verify"]:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

    return pg_dbapi.connect(
        user=cfg["user"],
        password=cfg["password"],
        host=cfg["host"],
        port=cfg["port"],
        database=cfg["database"],
        ssl_context=ssl_ctx,
        timeout=10,
    )


def _open_pg_connection(uri: str) -> _UnifiedConnection:
    return _UnifiedConnection(_open_pg_raw(uri), "postgres", uri=uri, from_pool=False)


def _acquire_pg_connection(uri: str) -> tuple[str, _UnifiedConnection]:
    pool_key = hashlib.sha1(uri.encode("utf-8")).hexdigest()[:16]
    now_mono = time.monotonic()
    with _PG_POOL_LOCK:
        bucket = _PG_POOL.get(pool_key)
        while bucket:
            conn, last_ts = bucket.pop()
            if (now_mono - last_ts) <= _PG_POOL_IDLE_TTL and not conn._broken:
                conn._from_pool = True
                conn._queries_run = 0
                return pool_key, conn
            conn.close()
    return pool_key, _open_pg_connection(uri)


def _release_pg_connection(pool_key: str, conn: _UnifiedConnection, healthy: bool):
    if not healthy or conn._broken:
        conn.close()
        return
    try:
        conn._raw.rollback()
    except Exception:
        conn.close()
        return
    conn._queries_run = 0
    conn._from_pool = True
    with _PG_POOL_LOCK:
        bucket = _PG_POOL.setdefault(pool_key, deque())
        if len(bucket) < _PG_POOL_MAX_PER_KEY:
            bucket.append((conn, time.monotonic()))
        else:
            conn.close()


def close_all_pooled_connections():
    """Menutup seluruh koneksi idle di pool PostgreSQL (berguna saat shutdown/testing)."""
    with _PG_POOL_LOCK:
        for bucket in _PG_POOL.values():
            while bucket:
                c, _ = bucket.popleft()
                c.close()
        _PG_POOL.clear()


def _open_sqlite_connection() -> _UnifiedConnection:
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    return _UnifiedConnection(raw, "sqlite")


@contextmanager
def _db_session():
    """Membuka koneksi database dengan pool persisten PostgreSQL (fallback ke SQLite lokal)."""
    global _LAST_CLOUD_ERROR
    db_url = get_database_url()
    conn = None
    pool_key = ""
    if db_url:
        try:
            pool_key, conn = _acquire_pg_connection(db_url)
            _LAST_CLOUD_ERROR = ""
        except Exception as exc:
            _LAST_CLOUD_ERROR = str(exc)
            try:
                from alert_manager import send_alert_to_phone
                send_alert_to_phone(f"Fallback SQLite: {exc}", context="Supabase DB Connection")
            except Exception:
                pass
            conn = _open_sqlite_connection()
            pool_key = ""
    else:
        _LAST_CLOUD_ERROR = ""
        conn = _open_sqlite_connection()

    had_error = False
    try:
        yield conn, conn.cursor()
    except Exception:
        had_error = True
        conn._broken = True
        raise
    finally:
        if conn.backend == "postgres" and pool_key:
            _release_pg_connection(pool_key, conn, healthy=(not had_error and not conn._broken))
        else:
            conn.close()


def get_storage_backend_info() -> dict:
    """Mengembalikan informasi status backend penyimpanan untuk ditampilkan ke Admin."""
    db_url = get_database_url()
    if db_url and not _LAST_CLOUD_ERROR and _HAS_PG8000:
        try:
            cfg = parse_database_url(db_url)
            return {
                "mode": "supabase",
                "label": "Cloud Permanen (Supabase PostgreSQL)",
                "host": cfg["host"],
                "error": "",
            }
        except Exception as exc:
            return {
                "mode": "sqlite_fallback",
                "label": "Mode Lokal SQLite (URI Cloud Tidak Valid)",
                "host": "",
                "error": str(exc),
            }
    if db_url and _LAST_CLOUD_ERROR:
        return {
            "mode": "sqlite_fallback",
            "label": "Mode Lokal SQLite (Fallback Koneksi Cloud)",
            "host": "",
            "error": _LAST_CLOUD_ERROR,
        }
    return {
        "mode": "sqlite",
        "label": "Mode Lokal (SQLite)",
        "host": "",
        "error": "",
    }


def get_local_now(tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> datetime:
    """Mengembalikan waktu lokal pengguna (default WITA UTC+8) agar tidak bergeser di server Cloud UTC."""
    try:
        offset = int(tz_offset)
    except (TypeError, ValueError):
        offset = DEFAULT_TIMEZONE_OFFSET
    offset = max(-12, min(14, offset))
    return (datetime.now(timezone.utc) + timedelta(hours=offset)).replace(tzinfo=None)


def _get_session_secret_key() -> bytes:
    """Mengambil atau membuat kunci HMAC sesi server secara aman tanpa hardcode di kode sumber."""
    env_sec = os.environ.get("SESSION_SECRET", "") or os.environ.get("GEMINI_API_KEY", "")
    if not env_sec:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "SESSION_SECRET" in st.secrets:
                    env_sec = st.secrets["SESSION_SECRET"]
                elif "GEMINI_API_KEY" in st.secrets:
                    env_sec = st.secrets["GEMINI_API_KEY"]
        except Exception:
            pass

    if env_sec:
        return hashlib.sha256(f"nutrisi_cerdas_hmac::{env_sec}".encode("utf-8")).digest()

    with _db_session() as (conn, cur):
        cur.execute("CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL)")
        row = cur.execute("SELECT meta_value FROM app_meta WHERE meta_key = 'session_hmac_secret'").fetchone()
        if row and row[0]:
            secret_hex = row[0]
        else:
            secret_hex = secrets.token_hex(32)
            cur.execute(
                """
                INSERT INTO app_meta (meta_key, meta_value) VALUES (?, ?)
                ON CONFLICT (meta_key) DO UPDATE SET meta_value = excluded.meta_value
                """,
                ("session_hmac_secret", secret_hex),
            )
            conn.commit()
    return secret_hex.encode("utf-8")


def create_session_token(user_id: str, ttl_seconds: int = SESSION_TOKEN_TTL_SECONDS) -> str:
    """Membuat token HMAC bertanda tangan dengan masa kedaluwarsa (default 30 hari)."""
    clean_id = (user_id or "").strip().lower()
    if is_guest_user_id(clean_id):
        return ""
    exp_ts = int(time.time()) + int(ttl_seconds)
    key = _get_session_secret_key()
    payload = f"{clean_id}|{exp_ts}".encode("utf-8")
    sig = hmac.new(key, payload, hashlib.sha256).hexdigest()[:24]
    return f"{exp_ts}.{sig}"


def verify_session_token(user_id: str, token: str) -> bool:
    """Memvalidasi integritas & masa berlaku token HMAC URL secara constant-time."""
    clean_id = (user_id or "").strip().lower()
    tok_str = str(token or "").strip()
    if is_guest_user_id(clean_id) or not tok_str or "." not in tok_str:
        return False
    exp_str, sig_str = tok_str.split(".", 1)
    if not exp_str.isdigit() or not sig_str:
        return False
    exp_ts = int(exp_str)
    now_ts = int(time.time())
    if exp_ts <= now_ts or exp_ts > (now_ts + SESSION_TOKEN_TTL_SECONDS + 300):
        return False
    key = _get_session_secret_key()
    expected = hmac.new(key, f"{clean_id}|{exp_ts}".encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return hmac.compare_digest(expected, sig_str)


def session_token_needs_refresh(token: str, refresh_window_seconds: int = 15 * 86400) -> bool:
    """Mengembalikan True bila token perlu diperbarui (hilang atau sisa masa aktif < 15 hari)."""
    tok_str = str(token or "").strip()
    if "." not in tok_str:
        return True
    exp_str = tok_str.split(".", 1)[0]
    if not exp_str.isdigit():
        return True
    return (int(exp_str) - int(time.time())) < refresh_window_seconds


def _create_tables_on_cursor(conn: _UnifiedConnection, cur: _UnifiedCursor):
    """Membuat seluruh skema tabel & migrasi kolom secara kompatibel di SQLite maupun PostgreSQL."""
    is_pg = (conn.backend == "postgres")
    pk_col = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    real_t = "DOUBLE PRECISION" if is_pg else "REAL"

    ddl_statements = [
        "CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL)",
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {pk_col},
            user_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            password_hash TEXT,
            avatar_url TEXT,
            auth_provider TEXT DEFAULT 'local',
            theme_preference TEXT DEFAULT 'Apple Light',
            daily_calorie_target {real_t} DEFAULT 2000.0,
            gender TEXT DEFAULT 'Pria',
            weight_kg {real_t} DEFAULT 65.0,
            height_cm {real_t} DEFAULT 170.0,
            age_years INTEGER DEFAULT 25,
            subscription_tier TEXT DEFAULT 'beta',
            pro_until TEXT,
            daily_scans_count INTEGER DEFAULT 0,
            last_scan_date TEXT,
            timezone_offset INTEGER DEFAULT 8,
            focus_goal TEXT DEFAULT 'Diet Sehat',
            fasting_mode TEXT DEFAULT 'Normal',
            created_at TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS meal_logs (
            id {pk_col},
            user_id TEXT NOT NULL,
            dish_name TEXT NOT NULL,
            energy_kcal {real_t} NOT NULL,
            protein_g {real_t} NOT NULL,
            fat_g {real_t} NOT NULL,
            carb_g {real_t} NOT NULL,
            fiber_g {real_t} NOT NULL,
            sodium_mg {real_t} DEFAULT 0.0,
            sugar_g {real_t} DEFAULT 0.0,
            portion_multiplier {real_t} DEFAULT 1.0,
            photo_caption TEXT,
            meal_type TEXT DEFAULT 'Makan Siang',
            logged_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meal_user_logged ON meal_logs(user_id, logged_at)",
        f"""
        CREATE TABLE IF NOT EXISTS water_logs (
            id {pk_col},
            user_id TEXT NOT NULL,
            log_date TEXT NOT NULL,
            glasses_count INTEGER DEFAULT 0,
            target_glasses INTEGER DEFAULT 8,
            updated_at TEXT,
            UNIQUE(user_id, log_date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_water_user_date ON water_logs(user_id, log_date)",
        f"""
        CREATE TABLE IF NOT EXISTS weight_logs (
            id {pk_col},
            user_id TEXT NOT NULL,
            weight_kg {real_t} NOT NULL,
            recorded_date TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT,
            UNIQUE(user_id, recorded_date)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_weight_user_date ON weight_logs(user_id, recorded_date)",
        f"""
        CREATE TABLE IF NOT EXISTS custom_foods (
            id {pk_col},
            user_id TEXT NOT NULL,
            food_name TEXT NOT NULL,
            serving_size TEXT DEFAULT '1 porsi',
            energy_kcal {real_t} NOT NULL,
            protein_g {real_t} DEFAULT 0.0,
            fat_g {real_t} DEFAULT 0.0,
            carb_g {real_t} DEFAULT 0.0,
            created_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_custom_food_user ON custom_foods(user_id)",
        f"""
        CREATE TABLE IF NOT EXISTS pending_foods (
            id {pk_col},
            food_name TEXT NOT NULL,
            category TEXT DEFAULT 'Produk Kemasan / Ritel',
            serving_unit TEXT DEFAULT '1 porsi (100g)',
            default_serving_weight {real_t} DEFAULT 100.0,
            energy_kcal {real_t} NOT NULL,
            protein_g {real_t} DEFAULT 0.0,
            fat_g {real_t} DEFAULT 0.0,
            carb_g {real_t} DEFAULT 0.0,
            fiber_g {real_t} DEFAULT 0.0,
            sodium_mg {real_t} DEFAULT 0.0,
            barcode TEXT,
            source_origin TEXT DEFAULT 'Open Food Facts / AI',
            submitted_by TEXT DEFAULT 'system',
            status TEXT DEFAULT 'pending',
            created_at TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS food_catalog_additions (
            id {pk_col},
            food_code TEXT UNIQUE NOT NULL,
            food_name TEXT UNIQUE NOT NULL,
            category TEXT,
            serving_unit TEXT DEFAULT '1 porsi',
            default_serving_weight {real_t} DEFAULT 100.0,
            bdd_rate {real_t} DEFAULT 100.0,
            energy_kcal {real_t} NOT NULL,
            protein_g {real_t} DEFAULT 0.0,
            fat_g {real_t} DEFAULT 0.0,
            carb_g {real_t} DEFAULT 0.0,
            fiber_g {real_t} DEFAULT 0.0,
            sodium_mg {real_t} DEFAULT 0.0,
            barcode TEXT,
            updated_at TEXT
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS payment_orders (
            id {pk_col},
            order_id TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            plan_code TEXT NOT NULL,
            amount_idr INTEGER NOT NULL,
            days INTEGER NOT NULL,
            provider TEXT DEFAULT 'qris',
            status TEXT DEFAULT 'pending',
            payment_url TEXT DEFAULT '',
            external_ref TEXT DEFAULT '',
            created_at TEXT,
            paid_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_payment_orders_user ON payment_orders(user_id, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS pro_vouchers (
            id {pk_col},
            code TEXT UNIQUE NOT NULL,
            plan_code TEXT DEFAULT 'PRO_30D',
            days INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            redeemed_by TEXT DEFAULT '',
            created_by TEXT DEFAULT 'admin',
            note TEXT DEFAULT '',
            created_at TEXT,
            redeemed_at TEXT
        )
        """,
    ]

    for stmt in ddl_statements:
        cur.execute(stmt)
    conn.commit()

    alter_columns = [
        ("users", "password_hash", "TEXT"),
        ("users", "gender", "TEXT DEFAULT 'Pria'"),
        ("users", "weight_kg", f"{real_t} DEFAULT 65.0"),
        ("users", "height_cm", f"{real_t} DEFAULT 170.0"),
        ("users", "age_years", "INTEGER DEFAULT 25"),
        ("users", "theme_preference", "TEXT DEFAULT 'Apple Light'"),
        ("users", "subscription_tier", "TEXT DEFAULT 'beta'"),
        ("users", "pro_until", "TEXT"),
        ("users", "daily_scans_count", "INTEGER DEFAULT 0"),
        ("users", "last_scan_date", "TEXT"),
        ("users", "timezone_offset", "INTEGER DEFAULT 8"),
        ("users", "focus_goal", "TEXT DEFAULT 'Diet Sehat'"),
        ("users", "fasting_mode", "TEXT DEFAULT 'Normal'"),
        ("meal_logs", "meal_type", "TEXT DEFAULT 'Makan Siang'"),
        ("meal_logs", "sodium_mg", f"{real_t} DEFAULT 0.0"),
        ("meal_logs", "sugar_g", f"{real_t} DEFAULT 0.0"),
        ("pending_foods", "sugar_g", f"{real_t} DEFAULT 0.0"),
        ("food_catalog_additions", "sugar_g", f"{real_t} DEFAULT 0.0"),
    ]
    for table, col_name, col_def in alter_columns:
        if is_pg:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col_name} {col_def}")
            conn.commit()
        else:
            try:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
                conn.commit()
            except Exception:
                pass


def _sync_cloud_catalog_to_sqlite(pg_cur: _UnifiedCursor, sq_cur=None, sq_conn=None):
    """Menarik tambahan katalog kurasi Admin dari cloud ke tkpi_nutrition.db lokal."""
    if not os.path.exists(DB_PATH):
        return
    own_sq = sq_conn is None
    if own_sq:
        sq_conn = sqlite3.connect(DB_PATH)
        sq_conn.row_factory = sqlite3.Row
        sq_cur = sq_conn.cursor()

    try:
        has_fc = sq_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='food_composition'").fetchone()
        if not has_fc:
            return
        cloud_foods = pg_cur.execute("SELECT * FROM food_catalog_additions").fetchall()
        if not cloud_foods:
            return
        for cf in cloud_foods:
            ex = sq_cur.execute(
                "SELECT id FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1",
                (cf["food_name"],),
            ).fetchone()
            if ex:
                sq_cur.execute(
                    """
                    UPDATE food_composition
                    SET category=?, serving_unit=?, default_serving_weight=?, energy_kcal=?,
                        protein_g=?, fat_g=?, carb_g=?, fiber_g=?, sodium_mg=?,
                        barcode=COALESCE(?, barcode)
                    WHERE id=?
                    """,
                    (
                        cf["category"], cf["serving_unit"], float(cf["default_serving_weight"] or 100.0),
                        float(cf["energy_kcal"]), float(cf["protein_g"] or 0.0), float(cf["fat_g"] or 0.0),
                        float(cf["carb_g"] or 0.0), float(cf["fiber_g"] or 0.0), float(cf["sodium_mg"] or 0.0),
                        cf["barcode"], ex["id"],
                    ),
                )
            else:
                sq_cur.execute(
                    """
                    INSERT INTO food_composition
                    (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate,
                     energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cf["food_code"], cf["food_name"], cf["category"], cf["serving_unit"],
                        float(cf["default_serving_weight"] or 100.0), float(cf["bdd_rate"] or 100.0),
                        float(cf["energy_kcal"]), float(cf["protein_g"] or 0.0), float(cf["fat_g"] or 0.0),
                        float(cf["carb_g"] or 0.0), float(cf["fiber_g"] or 0.0), float(cf["sodium_mg"] or 0.0),
                        cf["barcode"],
                    ),
                )
        sq_conn.commit()
        try:
            from nutrition_engine import invalidate_food_catalog_cache
            invalidate_food_catalog_cache()
        except Exception:
            pass
    finally:
        if own_sq:
            sq_conn.close()


def _sync_sqlite_seed_and_cloud_catalog(pg_conn: _UnifiedConnection, pg_cur: _UnifiedCursor):
    """Sinkronisasi idempoten: migrasi akun awal ke Supabase (batch 2 query) & tarik katalog cloud."""
    if not os.path.exists(DB_PATH):
        return

    sq = sqlite3.connect(DB_PATH)
    sq.row_factory = sqlite3.Row
    sq_cur = sq.cursor()

    try:
        # Cek cepat seluruh user_id & meal_logs yang sudah ada di cloud sekaligus (2 query, bukan per-user)
        existing_uids = {str(r[0]).lower() for r in pg_cur.execute("SELECT user_id FROM users").fetchall() if r[0]}
        cloud_meal_uids = {str(r[0]).lower() for r in pg_cur.execute("SELECT DISTINCT user_id FROM meal_logs").fetchall() if r[0]}

        local_users = sq_cur.execute("SELECT * FROM users").fetchall()
        for u in local_users:
            ud = dict(u)
            uid = ud.get("user_id")
            if not uid:
                continue
            if uid.lower() not in existing_uids:
                pg_cur.execute(
                    """
                    INSERT INTO users
                    (user_id, display_name, password_hash, avatar_url, auth_provider, theme_preference,
                     daily_calorie_target, gender, weight_kg, height_cm, age_years, subscription_tier,
                     pro_until, daily_scans_count, last_scan_date, timezone_offset, focus_goal, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (user_id) DO NOTHING
                    """,
                    (
                        uid,
                        ud.get("display_name"),
                        ud.get("password_hash"),
                        ud.get("avatar_url"),
                        ud.get("auth_provider") or "local",
                        ud.get("theme_preference") or "Apple Light",
                        float(ud.get("daily_calorie_target") or 2000.0),
                        ud.get("gender") or "Pria",
                        float(ud.get("weight_kg") or 65.0),
                        float(ud.get("height_cm") or 170.0),
                        int(ud.get("age_years") or 25),
                        ud.get("subscription_tier") or "beta",
                        ud.get("pro_until"),
                        int(ud.get("daily_scans_count") or 0),
                        ud.get("last_scan_date"),
                        int(ud.get("timezone_offset") if ud.get("timezone_offset") is not None else DEFAULT_TIMEZONE_OFFSET),
                        ud.get("focus_goal") or "Diet Sehat",
                        str(ud.get("created_at") or get_local_now().strftime("%Y-%m-%d %H:%M:%S")),
                    ),
                )
            if uid.lower() not in cloud_meal_uids:
                for ml in sq_cur.execute("SELECT * FROM meal_logs WHERE user_id = ?", (uid,)).fetchall():
                    md = dict(ml)
                    pg_cur.execute(
                        """
                        INSERT INTO meal_logs
                        (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg,
                         portion_multiplier, photo_caption, meal_type, logged_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            uid,
                            md.get("dish_name"),
                            float(md.get("energy_kcal") or 0.0),
                            float(md.get("protein_g") or 0.0),
                            float(md.get("fat_g") or 0.0),
                            float(md.get("carb_g") or 0.0),
                            float(md.get("fiber_g") or 0.0),
                            float(md.get("sodium_mg") or 0.0),
                            float(md.get("portion_multiplier") or 1.0),
                            md.get("photo_caption") or "",
                            md.get("meal_type") or "Makan Siang",
                            str(md.get("logged_at") or ""),
                        ),
                    )

        pg_conn.commit()
        _sync_cloud_catalog_to_sqlite(pg_cur, sq_cur=sq_cur, sq_conn=sq)
    except Exception:
        pg_conn.rollback()
    finally:
        sq.close()


def init_user_history_tables(force: bool = False):
    """Inisialisasi skema tabel secara cepat (melewati DDL jika SCHEMA_VERSION sudah terpasang)."""
    db_url = get_database_url()
    cache_key = f"pg::{hashlib.sha1(db_url.encode('utf-8')).hexdigest()[:12]}" if db_url else f"sqlite::{DB_PATH}"
    if not force and cache_key in _INITIALIZED_BACKENDS:
        return

    with _db_session() as (conn, cur):
        if conn.backend == "postgres" and not force:
            try:
                sv_row = cur.execute("SELECT meta_value FROM app_meta WHERE meta_key = 'schema_version'").fetchone()
                if sv_row and sv_row[0] == SCHEMA_VERSION:
                    _sync_cloud_catalog_to_sqlite(cur)
                    _INITIALIZED_BACKENDS.add(cache_key)
                    return
            except Exception:
                conn.rollback()

        _create_tables_on_cursor(conn, cur)
        if conn.backend == "postgres":
            _sync_sqlite_seed_and_cloud_catalog(conn, cur)
            cur.execute(
                """
                INSERT INTO app_meta (meta_key, meta_value) VALUES ('schema_version', ?)
                ON CONFLICT (meta_key) DO UPDATE SET meta_value = excluded.meta_value
                """,
                (SCHEMA_VERSION,),
            )
            conn.commit()
            _INITIALIZED_BACKENDS.add(cache_key)
        else:
            _INITIALIZED_BACKENDS.add(f"sqlite::{DB_PATH}")
    try:
        cleanup_stale_guest_users(max_age_days=7)
    except Exception:
        pass


def hash_password(password: str, salt_hex: str = None) -> str:
    """Hash aman PBKDF2-HMAC-SHA256 dengan salt acak per pengguna untuk PIN/Password."""
    if not password:
        return ""
    clean_pw = password.strip().encode("utf-8")
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", clean_pw, salt, 100_000)
    return f"pbkdf2${salt.hex()}${dk.hex()}"


def _verify_password(input_password: str, saved_hash: str) -> tuple[bool, bool]:
    """
    Memverifikasi PIN/Password terhadap format PBKDF2 baru maupun SHA-256 lama.
    Mengembalikan (is_valid, needs_upgrade).
    """
    if not saved_hash:
        return False, False
    clean_pw = (input_password or "").strip()
    if not clean_pw:
        return False, False
    if saved_hash.startswith("pbkdf2$"):
        parts = saved_hash.split("$")
        if len(parts) != 3:
            return False, False
        _, salt_hex, _ = parts
        candidate = hash_password(clean_pw, salt_hex=salt_hex)
        return hmac.compare_digest(candidate, saved_hash), False

    legacy_hex = hashlib.sha256(clean_pw.encode("utf-8")).hexdigest()
    is_valid = hmac.compare_digest(legacy_hex, saved_hash)
    return is_valid, is_valid


def is_admin_user(user_id: str) -> bool:
    """Mengecek secara ketat (exact match) apakah user adalah Founder / Admin aplikasi."""
    if not user_id:
        return False
    uid = user_id.strip().lower()
    return uid in ADMIN_IDENTIFIERS


def register_user(user_id: str, display_name: str, pin_or_pass: str, gender: str = "Pria", bb: float = 65.0, tb: float = 170.0, age: int = 25, target_kcal: float = 2000.0, focus_goal: str = "Diet Sehat", timezone_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Mendaftarkan akun baru dengan verifikasi PIN/Password aman PBKDF2 dan profil tubuh pribadi."""
    clean_id = (user_id or "").strip().lower()
    if is_guest_user_id(clean_id):
        return False, "ID Pengguna / Email tidak valid atau kosong."
    if not pin_or_pass or len(pin_or_pass.strip()) < 4:
        return False, "PIN / Password minimal 4 karakter agar akun Anda aman."
    ok_dname, dname_or_err = validate_display_name(display_name or "")
    if not ok_dname:
        return False, dname_or_err

    with _db_session() as (conn, cur):
        existing = cur.execute("SELECT id FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
        if existing:
            return False, "ID Pengguna / Email ini sudah terdaftar. Silakan login."

        p_hash = hash_password(pin_or_pass)
        is_admin = is_admin_user(clean_id)
        initial_tier = "pro" if is_admin else ("beta" if OPEN_BETA_MODE else "free")
        initial_expiry = "2099-12-31 23:59:59" if is_admin else None
        local_now = get_local_now(timezone_offset)
        now_str = local_now.strftime("%Y-%m-%d %H:%M:%S")

        cur.execute(
            """
            INSERT INTO users
            (user_id, display_name, password_hash, auth_provider, daily_calorie_target, gender, weight_kg, height_cm, age_years, subscription_tier, pro_until, timezone_offset, focus_goal, created_at)
            VALUES (?, ?, ?, 'local', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_id,
                (display_name or clean_id.split("@")[0].capitalize()).strip(),
                p_hash,
                float(target_kcal),
                gender,
                float(bb),
                float(tb),
                int(age),
                initial_tier,
                initial_expiry,
                int(timezone_offset),
                focus_goal,
                now_str,
            ),
        )

        if bb and float(bb) > 0:
            cur.execute(
                """
                INSERT INTO weight_logs (user_id, weight_kg, recorded_date, note, created_at)
                VALUES (?, ?, ?, 'Berat awal pendaftaran', ?)
                ON CONFLICT(user_id, recorded_date) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    note = excluded.note,
                    created_at = excluded.created_at
                """,
                (clean_id, round(float(bb), 1), local_now.strftime("%Y-%m-%d"), now_str),
            )

        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
        return True, dict(row)


def authenticate_user(user_id: str, pin_or_pass: str):
    """Memverifikasi login pengguna dengan ID dan PIN/Password (otomatis upgrade hash lama ke PBKDF2)."""
    clean_id = (user_id or "").strip().lower()
    if is_guest_user_id(clean_id):
        return False, "Ketikkan ID Pengguna / Email Anda."
    if not (pin_or_pass or "").strip():
        return False, "PIN / Password wajib diisi."

    with _db_session() as (conn, cur):
        user = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ? ORDER BY id ASC LIMIT 1", (clean_id,)).fetchone()
        if not user:
            return False, "Akun tidak ditemukan. Silakan klik 'Daftar Akun Baru'."

        u_dict = dict(user)
        saved_hash = u_dict.get("password_hash")
        if not saved_hash:
            return False, "Akun ini terhubung lewat Google/WhatsApp dan belum memakai PIN lokal. Gunakan Masuk Google atau daftar akun ber-PIN."

        valid, needs_upgrade = _verify_password(pin_or_pass, saved_hash)
        if not valid:
            return False, "PIN / Password salah! Silakan periksa kembali."
        if needs_upgrade:
            new_hash = hash_password(pin_or_pass)
            cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, u_dict["id"]))
            conn.commit()
            u_dict["password_hash"] = new_hash

        return True, u_dict


def _normalize_user_id(user_id: str) -> str:
    raw = (user_id or "").strip()
    if not raw or raw.lower() == "tamu (demo)":
        return "Tamu (Demo)"
    return raw.lower()


def get_or_create_user(user_id: str, display_name: str = "", auth_provider: str = "local"):
    """Mengambil data user atau membuat profil baru secara case-insensitive agar akun tidak terduplikasi."""
    norm_id = _normalize_user_id(user_id)
    is_guest = is_guest_user_id(norm_id)
    with _db_session() as (conn, cur):
        is_admin = is_admin_user(norm_id)
        initial_tier = "pro" if is_admin else ("beta" if (OPEN_BETA_MODE and not is_guest) else "demo")
        initial_expiry = "2099-12-31 23:59:59" if is_admin else None
        now_str = get_local_now(DEFAULT_TIMEZONE_OFFSET).strftime("%Y-%m-%d %H:%M:%S")

        row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ? ORDER BY id ASC LIMIT 1", (norm_id.lower(),)).fetchone()
        if not row:
            name = display_name or ("Tamu" if is_guest else norm_id.split("@")[0].capitalize())
            eff_provider = "guest" if (is_guest and norm_id.startswith(GUEST_PREFIX)) else auth_provider
            cur.execute(
                """
                INSERT INTO users (user_id, display_name, auth_provider, daily_calorie_target, subscription_tier, pro_until, timezone_offset, focus_goal, created_at)
                VALUES (?, ?, ?, 2000.0, ?, ?, ?, 'Diet Sehat', ?)
                """,
                (norm_id, name, eff_provider, initial_tier, initial_expiry, DEFAULT_TIMEZONE_OFFSET, now_str),
            )
            conn.commit()
            row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ? ORDER BY id ASC LIMIT 1", (norm_id.lower(),)).fetchone()
        elif is_admin and row["subscription_tier"] != "pro":
            cur.execute("UPDATE users SET subscription_tier = 'pro', pro_until = '2099-12-31 23:59:59' WHERE LOWER(user_id) = ?", (norm_id.lower(),))
            conn.commit()
            row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ? ORDER BY id ASC LIMIT 1", (norm_id.lower(),)).fetchone()

        return dict(row)


def migrate_guest_data_to_user(guest_uid: str, target_uid: str) -> dict:
    """Memindahkan catatan makan, air, berat badan, & makanan kustom dari sesi tamu terisolasi (guest_*) ke akun baru."""
    g_id = (guest_uid or "").strip().lower()
    t_id = _normalize_user_id(target_uid)
    moved = {"meals": 0, "water": 0, "weights": 0, "custom": 0}
    if not g_id.startswith(GUEST_PREFIX) or is_guest_user_id(t_id) or g_id == t_id:
        return moved

    with _db_session() as (conn, cur):
        meals = cur.execute("SELECT id FROM meal_logs WHERE user_id = ?", (g_id,)).fetchall()
        if meals:
            cur.execute("UPDATE meal_logs SET user_id = ? WHERE user_id = ?", (t_id, g_id))
            moved["meals"] = len(meals)

        water_rows = cur.execute("SELECT log_date, glasses_count, target_glasses, updated_at FROM water_logs WHERE user_id = ?", (g_id,)).fetchall()
        for wr in water_rows:
            ex_w = cur.execute("SELECT glasses_count FROM water_logs WHERE user_id = ? AND log_date = ?", (t_id, wr["log_date"])).fetchone()
            if ex_w:
                merged_g = max(0, int(ex_w[0] or 0) + int(wr["glasses_count"] or 0))
                cur.execute(
                    "UPDATE water_logs SET glasses_count = ?, updated_at = ? WHERE user_id = ? AND log_date = ?",
                    (merged_g, wr["updated_at"], t_id, wr["log_date"]),
                )
            else:
                cur.execute(
                    "INSERT INTO water_logs (user_id, log_date, glasses_count, target_glasses, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (t_id, wr["log_date"], int(wr["glasses_count"] or 0), int(wr["target_glasses"] or 8), wr["updated_at"]),
                )
            moved["water"] += 1
        cur.execute("DELETE FROM water_logs WHERE user_id = ?", (g_id,))

        wt_rows = cur.execute("SELECT recorded_date, weight_kg, note, created_at FROM weight_logs WHERE user_id = ?", (g_id,)).fetchall()
        for wtr in wt_rows:
            cur.execute(
                """
                INSERT INTO weight_logs (user_id, weight_kg, recorded_date, note, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, recorded_date) DO NOTHING
                """,
                (t_id, wtr["weight_kg"], wtr["recorded_date"], wtr["note"] or "", wtr["created_at"]),
            )
            moved["weights"] += 1
        cur.execute("DELETE FROM weight_logs WHERE user_id = ?", (g_id,))

        cf_rows = cur.execute("SELECT id FROM custom_foods WHERE user_id = ?", (g_id,)).fetchall()
        if cf_rows:
            cur.execute("UPDATE custom_foods SET user_id = ? WHERE user_id = ?", (t_id, g_id))
            moved["custom"] = len(cf_rows)

        cur.execute("DELETE FROM users WHERE user_id = ?", (g_id,))
        conn.commit()
    return moved


def cleanup_stale_guest_users(max_age_days: int = 7) -> int:
    """Menghapus sesi tamu terisolasi (guest_*) yang sudah lebih lama dari max_age_days agar DB tetap ramping."""
    cutoff_str = (get_local_now(DEFAULT_TIMEZONE_OFFSET) - timedelta(days=max_age_days)).strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        stale_rows = cur.execute(
            "SELECT user_id FROM users WHERE user_id LIKE ? AND COALESCE(created_at, '') < ?",
            (f"{GUEST_PREFIX}%", cutoff_str),
        ).fetchall()
        if not stale_rows:
            return 0
        for sr in stale_rows:
            gid = sr["user_id"]
            for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (gid,))
        conn.commit()
    return len(stale_rows)


def add_custom_food(user_id: str, food_name: str, serving_size: str, kcal: float, protein: float, fat: float, carb: float):
    """Menyimpan makanan manual buatan pengguna sendiri setelah lolos guardrail pangan."""
    clean_name = validate_food_candidate(
        food_name=food_name,
        energy_kcal=float(kcal or 0.0),
        protein_g=float(protein or 0.0),
        fat_g=float(fat or 0.0),
        carb_g=float(carb or 0.0),
        is_catalog_entry=False,
    )
    now_str = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        cur.execute(
            """
            INSERT INTO custom_foods (user_id, food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, clean_name, (serving_size or "1 porsi").strip()[:50], float(kcal), float(protein), float(fat), float(carb), now_str),
        )
        conn.commit()
    return True


def get_custom_foods(user_id: str):
    """Mengambil daftar makanan kustom yang pernah disimpan pengguna."""
    with _db_session() as (conn, cur):
        rows = cur.execute("SELECT * FROM custom_foods WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_custom_food(food_id: int, user_id: str):
    with _db_session() as (conn, cur):
        cur.execute("DELETE FROM custom_foods WHERE id = ? AND user_id = ?", (food_id, user_id))
        conn.commit()
    return True


def update_calorie_target(user_id: str, target_kcal: float):
    val = float(target_kcal)
    if not math.isfinite(val):
        raise ValueError("Target kalori harus berupa angka nyata.")
    bounded = max(800.0, min(5000.0, round(val, 1)))
    with _db_session() as (conn, cur):
        cur.execute("UPDATE users SET daily_calorie_target = ? WHERE user_id = ?", (bounded, user_id))
        conn.commit()


def update_user_theme(user_id: str, theme_name: str):
    """Menyimpan tema pilihan pengguna ke database permanen."""
    with _db_session() as (conn, cur):
        cur.execute("UPDATE users SET theme_preference = ? WHERE user_id = ?", (theme_name, user_id))
        conn.commit()


def update_user_preferences(user_id: str, timezone_offset: int = None, focus_goal: str = None, fasting_mode: str = None):
    """Memperbarui preferensi zona waktu (WIB/WITA/WIT), fokus kesehatan, dan mode puasa pengguna."""
    with _db_session() as (conn, cur):
        if timezone_offset is not None:
            cur.execute("UPDATE users SET timezone_offset = ? WHERE user_id = ?", (int(timezone_offset), user_id))
        if focus_goal is not None:
            cur.execute("UPDATE users SET focus_goal = ? WHERE user_id = ?", (focus_goal.strip(), user_id))
        if fasting_mode is not None:
            clean_fm = fasting_mode.strip()
            if clean_fm in VALID_FASTING_MODES:
                cur.execute("UPDATE users SET fasting_mode = ? WHERE user_id = ?", (clean_fm, user_id))
        conn.commit()
    return True


def update_user_body_profile(
    user_id: str,
    display_name: str = None,
    gender: str = None,
    weight_kg: float = None,
    height_cm: float = None,
    age_years: int = None,
    daily_calorie_target: float = None,
) -> tuple[bool, dict | str]:
    """Memperbarui profil tubuh & nama tampilan pengguna secara aman dengan validasi batas & XSS."""
    norm_id = _normalize_user_id(user_id)
    updates = []
    params = []

    if display_name is not None:
        ok_name, clean_or_err = validate_display_name(display_name)
        if not ok_name:
            return False, clean_or_err
        updates.append("display_name = ?")
        params.append(clean_or_err)
    if gender is not None and gender in {"Pria", "Wanita"}:
        updates.append("gender = ?")
        params.append(gender)
    if weight_kg is not None:
        w = max(20.0, min(250.0, round(float(weight_kg), 1)))
        updates.append("weight_kg = ?")
        params.append(w)
    if height_cm is not None:
        h = max(80.0, min(230.0, round(float(height_cm), 1)))
        updates.append("height_cm = ?")
        params.append(h)
    if age_years is not None:
        a = max(5, min(110, int(age_years)))
        updates.append("age_years = ?")
        params.append(a)
    if daily_calorie_target is not None:
        k = max(800.0, min(5000.0, round(float(daily_calorie_target), 1)))
        updates.append("daily_calorie_target = ?")
        params.append(k)

    if not updates:
        return False, "Tidak ada perubahan profil untuk disimpan."

    with _db_session() as (conn, cur):
        params.append(norm_id)
        cur.execute(f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?", tuple(params))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (norm_id,)).fetchone()
    if not row:
        return False, "Akun pengguna tidak ditemukan."
    return True, dict(row)


def change_user_password(user_id: str, current_pin: str, new_pin: str) -> tuple[bool, str]:
    """Mengganti PIN/Password akun lokal (atau menetapkan PIN awal untuk akun Google/WA)."""
    clean_id = (user_id or "").strip().lower()
    if is_guest_user_id(clean_id):
        return False, "Akun tamu tidak memiliki PIN. Buat akun terlebih dahulu."
    clean_new = (new_pin or "").strip()
    if len(clean_new) < 4:
        return False, "PIN atau password baru minimal 4 karakter."

    with _db_session() as (conn, cur):
        row = cur.execute("SELECT id, password_hash FROM users WHERE LOWER(user_id) = ? LIMIT 1", (clean_id,)).fetchone()
        if not row:
            return False, "Akun tidak ditemukan."
        saved_hash = row["password_hash"]
        if saved_hash:
            valid, _ = _verify_password(current_pin, saved_hash)
            if not valid:
                return False, "PIN / Password saat ini tidak cocok."
        new_hash = hash_password(clean_new)
        cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, row["id"]))
        conn.commit()
    return True, "PIN / Password berhasil diperbarui."


def log_weight_entry(user_id: str, weight_kg: float, note: str = "", tz_offset: int = DEFAULT_TIMEZONE_OFFSET, recorded_date: str = None):
    """Mencatat atau memperbarui berat badan harian ke tabel weight_logs sekaligus sinkron profil user."""
    raw_w = float(weight_kg)
    if not math.isfinite(raw_w):
        return False
    clean_w = round(raw_w, 1)
    if clean_w < 20.0 or clean_w > 300.0:
        return False
    local_now = get_local_now(tz_offset)
    r_date = recorded_date or local_now.strftime("%Y-%m-%d")
    now_str = local_now.strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        cur.execute(
            """
            INSERT INTO weight_logs (user_id, weight_kg, recorded_date, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, recorded_date) DO UPDATE SET
                weight_kg = excluded.weight_kg,
                note = excluded.note,
                created_at = excluded.created_at
            """,
            (user_id, clean_w, r_date, note or "", now_str),
        )
        cur.execute("UPDATE users SET weight_kg = ? WHERE user_id = ?", (clean_w, user_id))
        conn.commit()
    return True


def get_weight_history(user_id: str, limit: int = 30):
    """Mengambil histori berat badan pengguna secara kronologis untuk grafik progres."""
    with _db_session() as (conn, cur):
        rows = cur.execute(
            """
            SELECT recorded_date, weight_kg, note
            FROM weight_logs
            WHERE user_id = ?
            ORDER BY recorded_date ASC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_logging_streak(user_id: str, tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> int:
    """Menghitung jumlah hari berturut-turut (streak) pengguna mencatat makanan."""
    local_today = get_local_now(tz_offset).date()
    today_limit = local_today.strftime("%Y-%m-%d")
    with _db_session() as (conn, cur):
        rows = cur.execute(
            """
            SELECT DISTINCT SUBSTR(CAST(logged_at AS TEXT), 1, 10) AS d
            FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) <= ?
            ORDER BY d DESC
            """,
            (user_id, today_limit),
        ).fetchall()

    if not rows:
        return 0

    logged_dates = set()
    for r in rows:
        if r[0]:
            try:
                logged_dates.add(datetime.strptime(str(r[0])[:10], "%Y-%m-%d").date())
            except ValueError:
                pass
    cursor_day = local_today if local_today in logged_dates else (local_today - timedelta(days=1))
    streak = 0
    while cursor_day in logged_dates:
        streak += 1
        cursor_day -= timedelta(days=1)
    return streak


def log_water_intake(user_id: str, delta_glasses: int = 1, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Menambah atau mengurangi asupan air minum hari ini (+1 atau -1 gelas) dengan target adaptif."""
    local_now = get_local_now(tz_offset)
    today_str = local_now.strftime("%Y-%m-%d")
    now_str = local_now.strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        u_row = cur.execute("SELECT weight_kg, focus_goal FROM users WHERE user_id = ?", (user_id,)).fetchone()
        rec_target = compute_water_target_glasses(
            u_row["weight_kg"] if u_row else 65.0,
            u_row["focus_goal"] if u_row else "Diet Sehat",
        )
        row = cur.execute("SELECT glasses_count FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str)).fetchone()
        if row:
            new_count = max(0, int(row[0]) + delta_glasses)
            cur.execute(
                "UPDATE water_logs SET glasses_count = ?, target_glasses = ?, updated_at = ? WHERE user_id = ? AND log_date = ?",
                (new_count, rec_target, now_str, user_id, today_str),
            )
        else:
            new_count = max(0, delta_glasses)
            cur.execute(
                "INSERT INTO water_logs (user_id, log_date, glasses_count, target_glasses, updated_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, today_str, new_count, rec_target, now_str),
            )
        conn.commit()
    return new_count


def get_water_intake(user_id: str, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Mengambil progres air minum hari ini dengan target adaptif berat badan & fokus klinis."""
    today_str = get_local_now(tz_offset).strftime("%Y-%m-%d")
    with _db_session() as (conn, cur):
        u_row = cur.execute("SELECT weight_kg, focus_goal FROM users WHERE user_id = ?", (user_id,)).fetchone()
        rec_target = compute_water_target_glasses(
            u_row["weight_kg"] if u_row else 65.0,
            u_row["focus_goal"] if u_row else "Diet Sehat",
        )
        row = cur.execute("SELECT glasses_count, target_glasses FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str)).fetchone()
    glasses = int(row[0]) if row else 0
    return {"glasses": glasses, "target": rec_target, "ml": glasses * 250, "target_ml": rec_target * 250}


def _compute_scan_status_from_row(user_row, user_id: str, tz_offset: int = None) -> dict:
    """Menghitung kuota scan harian secara murni dari baris tabel users yang sudah diambil."""
    u_dict = dict(user_row) if user_row else None
    effective_tz = tz_offset if tz_offset is not None else (
        u_dict["timezone_offset"] if u_dict and u_dict.get("timezone_offset") is not None else DEFAULT_TIMEZONE_OFFSET
    )
    local_now = get_local_now(effective_tz)

    if not u_dict:
        return {"tier": "demo", "scans_today": 0, "max_scans": GUEST_DAILY_SCAN_LIMIT, "can_scan": True, "is_pro": False, "is_beta": False, "days_left": 0}

    is_admin = is_admin_user(user_id)
    is_guest = is_guest_user_id(user_id)
    tier = u_dict.get("subscription_tier") or ("demo" if is_guest else "beta")
    pro_until_str = u_dict.get("pro_until")

    is_pro = False
    days_left = 0
    if is_admin:
        is_pro = True
        days_left = 9999
    elif tier == "pro" and pro_until_str:
        try:
            exp_dt = datetime.strptime(str(pro_until_str)[:19], "%Y-%m-%d %H:%M:%S")
            if exp_dt > local_now:
                is_pro = True
                days_left = (exp_dt - local_now).days + 1
        except Exception:
            pass

    is_beta = False
    if is_admin:
        max_scans = 999999
        tier = "pro"
    elif is_pro:
        max_scans = 999999
        tier = "pro"
    elif OPEN_BETA_MODE:
        max_scans = GUEST_DAILY_SCAN_LIMIT if is_guest else BETA_DAILY_SCAN_LIMIT
        is_beta = not is_guest
        tier = "demo" if is_guest else "beta"
    else:
        max_scans = GUEST_DAILY_SCAN_LIMIT

    today_str = local_now.strftime("%Y-%m-%d")
    last_date = u_dict.get("last_scan_date")
    scans_today = int(u_dict.get("daily_scans_count") or 0)
    if last_date != today_str:
        scans_today = 0

    can_scan = True if (is_admin or is_pro) else (scans_today < max_scans)

    return {
        "tier": tier,
        "scans_today": scans_today,
        "max_scans": max_scans,
        "can_scan": can_scan,
        "is_pro": is_pro,
        "is_beta": is_beta,
        "days_left": days_left,
        "pro_until": str(pro_until_str or ""),
    }


def get_user_scan_status(user_id: str, tz_offset: int = None):
    """
    Memeriksa kuota scan foto harian user:
    - Admin: Unlimited
    - Open Beta (akun terdaftar): 5x scan foto/hari (3x makan berat + 2x jajan)
    - Tamu (Demo): 3x scan foto/hari
    """
    with _db_session() as (conn, cur):
        user = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return _compute_scan_status_from_row(user, user_id, tz_offset=tz_offset)


def record_scan_usage(user_id: str, tz_offset: int = None):
    """Mencatat 1 kali pemakaian scan foto makanan pada tanggal lokal pengguna."""
    with _db_session() as (conn, cur):
        row = cur.execute("SELECT last_scan_date, daily_scans_count, timezone_offset FROM users WHERE user_id = ?", (user_id,)).fetchone()
        effective_tz = tz_offset if tz_offset is not None else (row["timezone_offset"] if row and row["timezone_offset"] is not None else DEFAULT_TIMEZONE_OFFSET)
        today_str = get_local_now(effective_tz).strftime("%Y-%m-%d")
        if row:
            last_date, count = row["last_scan_date"], int(row["daily_scans_count"] or 0)
            new_count = 1 if last_date != today_str else count + 1
            cur.execute("UPDATE users SET last_scan_date = ?, daily_scans_count = ? WHERE user_id = ?", (today_str, new_count, user_id))
        conn.commit()


def _compute_stacked_pro_expiry(cur, clean_uid: str, days: int) -> str:
    """Menghitung tanggal kedaluwarsa Pro baru secara stacking (menambah sisa hari aktif jika belum habis)."""
    safe_days = max(1, min(1095, int(days or 30)))
    now_dt = get_local_now(DEFAULT_TIMEZONE_OFFSET)
    base_dt = now_dt
    row = cur.execute("SELECT subscription_tier, pro_until FROM users WHERE LOWER(user_id) = ? LIMIT 1", (clean_uid,)).fetchone()
    if row and row["subscription_tier"] == "pro" and row["pro_until"]:
        try:
            cur_exp = datetime.strptime(str(row["pro_until"])[:19], "%Y-%m-%d %H:%M:%S")
            if cur_exp > now_dt:
                base_dt = cur_exp
        except Exception:
            pass
    return (base_dt + timedelta(days=safe_days)).strftime("%Y-%m-%d %H:%M:%S")


def activate_pro_tier(user_id: str, days: int = 30):
    """Mengaktifkan atau memperpanjang (stacking) langganan Pro untuk pengguna terdaftar."""
    clean_uid = _normalize_user_id(user_id)
    if is_guest_user_id(clean_uid):
        raise ValueError("Sesi tamu harus mendaftar akun terlebih dahulu sebelum mengaktifkan Paket Pro.")
    with _db_session() as (conn, cur):
        expiry = _compute_stacked_pro_expiry(cur, clean_uid, days)
        cur.execute(
            "UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE LOWER(user_id) = ?",
            (expiry, clean_uid),
        )
        conn.commit()
    return expiry


def create_payment_order(
    user_id: str,
    plan_code: str,
    amount_idr: int,
    days: int,
    provider: str = "qris",
    payment_url: str = "",
    external_ref: str = "",
    order_id: str = "",
) -> dict:
    """Mencatat pesanan upgrade Paket Pro QRIS di tabel payment_orders."""
    clean_uid = _normalize_user_id(user_id)
    if is_guest_user_id(clean_uid):
        raise ValueError("Masuk atau buat akun terlebih dahulu sebelum membuat pesanan Pro.")
    safe_plan = str(plan_code or "PRO_30D").strip().upper()[:24]
    safe_amt = max(0, int(amount_idr or 0))
    safe_days = max(1, min(1095, int(days or 30)))
    now_dt = get_local_now(DEFAULT_TIMEZONE_OFFSET)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    oid = (order_id or f"NC-{safe_plan}-{now_dt.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}").strip()[:48]
    with _db_session() as (conn, cur):
        cur.execute(
            """
            INSERT INTO payment_orders
            (order_id, user_id, plan_code, amount_idr, days, provider, status, payment_url, external_ref, created_at, paid_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, NULL)
            """,
            (oid, clean_uid, safe_plan, safe_amt, safe_days, str(provider or "qris")[:30], str(payment_url or "")[:500], str(external_ref or "")[:120], now_str),
        )
        conn.commit()
        row = cur.execute("SELECT * FROM payment_orders WHERE order_id = ?", (oid,)).fetchone()
    return dict(row)


def get_payment_order(order_id: str) -> dict | None:
    oid = str(order_id or "").strip()
    if not oid:
        return None
    with _db_session() as (conn, cur):
        row = cur.execute("SELECT * FROM payment_orders WHERE order_id = ?", (oid,)).fetchone()
    return dict(row) if row else None


def mark_payment_order_paid(
    order_id: str,
    external_ref: str = "",
    expected_amount: int | None = None,
) -> tuple[bool, dict | str]:
    """Menandai pesanan lunas secara idempoten + mengaktifkan/memperpanjang Paket Pro dalam 1 transaksi atomik."""
    oid = str(order_id or "").strip()
    if not oid:
        return False, "Nomor order tidak boleh kosong."
    now_str = get_local_now(DEFAULT_TIMEZONE_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        row = cur.execute("SELECT * FROM payment_orders WHERE order_id = ?", (oid,)).fetchone()
        if not row:
            return False, f"Pesanan {oid} tidak ditemukan."
        order = dict(row)
        if expected_amount is not None and int(order["amount_idr"]) > 0 and int(expected_amount) < int(order["amount_idr"]):
            return False, f"Nominal pembayaran tidak sesuai (diterima Rp{int(expected_amount):,}, tagihan Rp{int(order['amount_idr']):,})."
        if order["status"] == "paid":
            # Idempoten: webhook berulang tidak menggandakan masa aktif
            return True, order

        clean_uid = _normalize_user_id(order["user_id"])
        expiry = _compute_stacked_pro_expiry(cur, clean_uid, int(order["days"]))
        cur.execute(
            "UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE LOWER(user_id) = ?",
            (expiry, clean_uid),
        )
        ref_val = str(external_ref or order.get("external_ref") or "").strip()[:120]
        cur.execute(
            "UPDATE payment_orders SET status = 'paid', external_ref = ?, paid_at = ? WHERE order_id = ?",
            (ref_val, now_str, oid),
        )
        conn.commit()
        upd = cur.execute("SELECT * FROM payment_orders WHERE order_id = ?", (oid,)).fetchone()
    res = dict(upd)
    res["pro_until"] = expiry
    return True, res


def list_user_payment_orders(user_id: str, limit: int = 10) -> list[dict]:
    clean_uid = _normalize_user_id(user_id)
    with _db_session() as (conn, cur):
        rows = cur.execute(
            "SELECT * FROM payment_orders WHERE LOWER(user_id) = ? ORDER BY id DESC LIMIT ?",
            (clean_uid, max(1, min(50, int(limit or 10)))),
        ).fetchall()
    return [dict(r) for r in rows]


def list_recent_payment_orders(limit: int = 30) -> list[dict]:
    with _db_session() as (conn, cur):
        rows = cur.execute(
            "SELECT * FROM payment_orders ORDER BY id DESC LIMIT ?",
            (max(1, min(100, int(limit or 30))),),
        ).fetchall()
    return [dict(r) for r in rows]


def create_pro_voucher(
    days: int = 30,
    plan_code: str = "PRO_30D",
    max_uses: int = 1,
    created_by: str = "admin",
    note: str = "",
    custom_code: str = "",
) -> dict:
    """Membuat kode voucher aktivasi Pro yang aman (bebas karakter ambigu 0/O/1/I)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    clean_custom = "".join(ch for ch in str(custom_code or "").upper().strip() if ch.isalnum() or ch == "-")[:32]
    if clean_custom:
        code = clean_custom
    else:
        part1 = "".join(secrets.choice(alphabet) for _ in range(4))
        part2 = "".join(secrets.choice(alphabet) for _ in range(4))
        code = f"NCPRO-{part1}-{part2}"
    safe_days = max(1, min(1095, int(days or 30)))
    safe_max = max(1, min(500, int(max_uses or 1)))
    now_str = get_local_now(DEFAULT_TIMEZONE_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        cur.execute(
            """
            INSERT INTO pro_vouchers
            (code, plan_code, days, max_uses, used_count, redeemed_by, created_by, note, created_at, redeemed_at)
            VALUES (?, ?, ?, ?, 0, '', ?, ?, ?, NULL)
            """,
            (code, str(plan_code or "PRO_30D")[:24], safe_days, safe_max, str(created_by or "admin")[:60], str(note or "")[:120], now_str),
        )
        conn.commit()
        row = cur.execute("SELECT * FROM pro_vouchers WHERE code = ?", (code,)).fetchone()
    return dict(row)


def redeem_pro_voucher(user_id: str, raw_code: str) -> tuple[bool, dict | str]:
    """Menukarkan kode aktivasi/voucher Pro secara atomik dengan proteksi anti-ganda."""
    clean_uid = _normalize_user_id(user_id)
    if is_guest_user_id(clean_uid):
        return False, "Buat akun gratis atau masuk terlebih dahulu agar masa aktif Pro tersimpan di akun Anda."
    code = str(raw_code or "").strip().upper()
    if len(code) < 5:
        return False, "Masukkan kode aktivasi Pro yang valid."
    now_dt = get_local_now(DEFAULT_TIMEZONE_OFFSET)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        row = cur.execute("SELECT * FROM pro_vouchers WHERE UPPER(code) = ?", (code,)).fetchone()
        if not row:
            return False, "Kode aktivasi tidak ditemukan. Periksa kembali huruf dan tanda hubungnya."
        v = dict(row)
        used = int(v.get("used_count") or 0)
        max_u = int(v.get("max_uses") or 1)
        prev_users = [u.strip().lower() for u in str(v.get("redeemed_by") or "").split(",") if u.strip()]
        if clean_uid in prev_users:
            return False, "Kode aktivasi ini sudah pernah Anda gunakan."
        if used >= max_u:
            return False, "Kuota pemakaian kode aktivasi ini sudah habis."

        days = int(v["days"])
        expiry = _compute_stacked_pro_expiry(cur, clean_uid, days)
        cur.execute(
            "UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE LOWER(user_id) = ?",
            (expiry, clean_uid),
        )
        prev_users.append(clean_uid)
        cur.execute(
            "UPDATE pro_vouchers SET used_count = ?, redeemed_by = ?, redeemed_at = ? WHERE id = ?",
            (used + 1, ",".join(prev_users)[:500], now_str, v["id"]),
        )
        audit_oid = f"NC-VCH-{now_dt.strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}"
        cur.execute(
            """
            INSERT INTO payment_orders
            (order_id, user_id, plan_code, amount_idr, days, provider, status, payment_url, external_ref, created_at, paid_at)
            VALUES (?, ?, ?, 0, ?, 'voucher', 'paid', '', ?, ?, ?)
            """,
            (audit_oid, clean_uid, v.get("plan_code") or "PRO_30D", days, code, now_str, now_str),
        )
        conn.commit()
    return True, {"code": code, "days": days, "pro_until": expiry, "order_id": audit_oid}


def list_pro_vouchers(limit: int = 25) -> list[dict]:
    with _db_session() as (conn, cur):
        rows = cur.execute(
            "SELECT * FROM pro_vouchers ORDER BY id DESC LIMIT ?",
            (max(1, min(100, int(limit or 25))),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_growth_metrics_summary() -> dict:
    """Menghitung metrik pertumbuhan nyata untuk panel Admin (progres target 100 pengguna aktif & pendapatan Pro)."""
    now_dt = get_local_now(DEFAULT_TIMEZONE_OFFSET)
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    cutoff_7d = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    with _db_session() as (conn, cur):
        user_rows = cur.execute("SELECT user_id, subscription_tier, pro_until FROM users").fetchall()
        reg_uids = [str(r["user_id"]) for r in user_rows if not is_guest_user_id(r["user_id"]) and not is_admin_user(r["user_id"])]
        active_pro = 0
        for r in user_rows:
            uid = str(r["user_id"])
            if is_guest_user_id(uid) or is_admin_user(uid):
                continue
            if r["subscription_tier"] == "pro" and r["pro_until"] and str(r["pro_until"])[:19] > now_str:
                active_pro += 1

        meal_rows = cur.execute(
            "SELECT DISTINCT user_id FROM meal_logs WHERE logged_at >= ?",
            (cutoff_7d,),
        ).fetchall()
        active_7d = sum(1 for mr in meal_rows if not is_guest_user_id(mr["user_id"]) and not is_admin_user(mr["user_id"]))

        ord_rows = cur.execute("SELECT status, amount_idr FROM payment_orders").fetchall()
        paid_cnt = sum(1 for o in ord_rows if o["status"] == "paid")
        paid_rev = sum(int(o["amount_idr"] or 0) for o in ord_rows if o["status"] == "paid")
        pending_cnt = sum(1 for o in ord_rows if o["status"] == "pending")

    return {
        "total_registered_users": len(reg_uids),
        "target_users": 100,
        "active_7d_users": active_7d,
        "active_pro_users": active_pro,
        "paid_orders_count": paid_cnt,
        "paid_revenue_idr": paid_rev,
        "pending_orders_count": pending_cnt,
    }


def _validate_meal_nutrients(
    dish_name: str,
    totals: dict,
    validate_name: bool = True,
    check_macro_atwater: bool = False,
    raw_item: dict = None,
) -> tuple[str, dict]:
    """Memvalidasi nama hidangan dan kewajaran nilai gizi (bebas negatif/NaN/ekstrem)."""
    clean_dish = " ".join(str(dish_name or "").strip().split())
    if validate_name:
        clean_dish = validate_food_text_query(clean_dish)
    elif not clean_dish:
        raise FoodGuardrailRejected("non_food", "Nama makanan tidak boleh kosong.")

    src = raw_item if raw_item is not None else (totals or {})
    for k in ("energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "sodium_mg", "sugar_g"):
        v_raw = src.get(k)
        if v_raw not in (None, ""):
            try:
                v_num = float(v_raw)
            except (TypeError, ValueError):
                raise FoodGuardrailRejected("invalid_nutrition", f"Nilai '{k}' tidak valid secara numerik.")
            if not math.isfinite(v_num) or v_num < 0:
                raise FoodGuardrailRejected("invalid_nutrition", "Angka nutrisi tidak boleh negatif atau NaN/Infinity.")

    kcal = _safe_float(src.get("energy_kcal"), 0.0)
    prot = _safe_float(src.get("protein_g"), 0.0)
    fat = _safe_float(src.get("fat_g"), 0.0)
    carb = _safe_float(src.get("carb_g"), 0.0)
    fib = _safe_float(src.get("fiber_g"), 0.0)
    sod = _safe_float(src.get("sodium_mg"), 0.0)
    sug = _safe_float(src.get("sugar_g"), 0.0)

    if kcal < 0 or kcal > (MAX_SINGLE_DISH_KCAL * 1.5):
        raise FoodGuardrailRejected(
            "implausible_portion",
            f"Kalori satu catatan ({kcal:,.1f} kkal) melebihi batas wajar per sajian.",
        )
    if prot > 250.0 or fat > 250.0 or carb > 600.0 or fib > 150.0 or sod > 25000.0 or sug > 300.0:
        raise FoodGuardrailRejected("invalid_nutrition", "Nilai makronutrien/serat/natrium/gula melebihi batas wajar sajian.")

    if check_macro_atwater:
        has_macros = any(src.get(k) not in (None, "") for k in ("protein_g", "fat_g", "carb_g"))
        if has_macros:
            macro_sum = prot + fat + carb
            atwater_kcal = (4.0 * prot) + (9.0 * fat) + (4.0 * carb)
            if kcal >= 150.0 and macro_sum < (kcal / 12.0):
                raise FoodGuardrailRejected(
                    "invalid_nutrition",
                    "Angka kalori tinggi dengan makronutrien hampir nol tidak konsisten secara ilmiah.",
                )
            if macro_sum >= 15.0 and atwater_kcal > 0 and kcal > max(atwater_kcal * 2.2 + 120.0, 300.0):
                raise FoodGuardrailRejected(
                    "invalid_nutrition",
                    "Angka kalori tidak selaras dengan perhitungan Atwater (4P + 9L + 4K).",
                )

    return clean_dish, {
        "energy_kcal": round(kcal, 1),
        "protein_g": round(prot, 1),
        "fat_g": round(fat, 1),
        "carb_g": round(carb, 1),
        "fiber_g": round(fib, 1),
        "sodium_mg": round(sod, 1),
        "sugar_g": round(sug, 1),
    }


def _get_daily_meal_usage(cur: _UnifiedCursor, user_id: str, target_date: str, exclude_log_id: int = None) -> tuple[int, float]:
    """Mengambil jumlah catatan makan & akumulasi kalori pada tanggal tertentu."""
    if exclude_log_id is not None:
        day_row = cur.execute(
            """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(energy_kcal), 0.0) AS tot_k
            FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ? AND id != ?
            """,
            (user_id, target_date, exclude_log_id),
        ).fetchone()
    else:
        day_row = cur.execute(
            """
            SELECT COUNT(*) AS cnt, COALESCE(SUM(energy_kcal), 0.0) AS tot_k
            FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ?
            """,
            (user_id, target_date),
        ).fetchone()
    if not day_row:
        return 0, 0.0
    return int(day_row[0] or 0), float(day_row[1] or 0.0)


def _check_daily_meal_budget(cur: _UnifiedCursor, user_id: str, target_date: str, add_kcal: float, add_count: int = 1, exclude_log_id: int = None):
    """Menjaga batas maksimal catatan makan & kalori harian tidak terlewati."""
    cur_cnt, cur_kcal = _get_daily_meal_usage(cur, user_id, target_date, exclude_log_id=exclude_log_id)
    if (cur_cnt + add_count) > MAX_DAILY_MEALS_PER_USER:
        raise FoodGuardrailRejected(
            "daily_cap_exceeded",
            f"Batas maksimal {MAX_DAILY_MEALS_PER_USER} catatan makan per hari tercapai untuk menjaga konsistensi diary.",
        )
    if (cur_kcal + add_kcal) > MAX_DAILY_KCAL_PER_USER:
        raise FoodGuardrailRejected(
            "daily_cap_exceeded",
            f"Akumulasi kalori harian akan melebihi batas biologis {MAX_DAILY_KCAL_PER_USER:,.0f} kkal/hari.",
        )


def log_meal(user_id: str, dish_name: str, totals: dict, multiplier: float = 1.0, caption: str = "", meal_type: str = "Makan Siang", log_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Menyimpan satu catatan makan ke buku harian pengguna dengan penjagaan batas biologis harian."""
    local_now = get_local_now(tz_offset)
    target_d = log_date or local_now.strftime("%Y-%m-%d")
    custom_timestamp = f"{target_d} {local_now.strftime('%H:%M:%S')}"
    clean_dish, clean_tot = _validate_meal_nutrients(dish_name, totals, validate_name=True)
    mult_val = _safe_float(multiplier, 1.0)
    if mult_val <= 0 or mult_val > 5.0:
        raise FoodGuardrailRejected("implausible_portion", "Pengali porsi harus berada di antara 0.1x hingga 5.0x.")

    with _db_session() as (conn, cur):
        _check_daily_meal_budget(cur, user_id, target_d, add_kcal=clean_tot["energy_kcal"], add_count=1)
        cur.execute(
            """
            INSERT INTO meal_logs
            (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, sugar_g, portion_multiplier, photo_caption, meal_type, logged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                clean_dish,
                clean_tot["energy_kcal"],
                clean_tot["protein_g"],
                clean_tot["fat_g"],
                clean_tot["carb_g"],
                clean_tot["fiber_g"],
                clean_tot["sodium_mg"],
                clean_tot["sugar_g"],
                mult_val,
                caption,
                meal_type,
                custom_timestamp,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
    return {
        "id": new_id,
        "user_id": user_id,
        "dish_name": clean_dish,
        "energy_kcal": clean_tot["energy_kcal"],
        "meal_type": meal_type,
        "saved_at": local_now.strftime("%H:%M")
    }


def update_meal_log(log_id: int, user_id: str, dish_name: str = None, totals: dict = None, multiplier: float = None, meal_type: str = None, caption: str = None):
    """Memperbarui catatan makan yang sudah ada sekaligus menjaga batas kalori harian dan guardrail pangan."""
    with _db_session() as (conn, cur):
        row = cur.execute("SELECT * FROM meal_logs WHERE id = ? AND user_id = ?", (log_id, user_id)).fetchone()
        if not row:
            return None

        cur_row = dict(row)
        raw_dish = dish_name if dish_name is not None else cur_row["dish_name"]
        new_meal_type = meal_type if meal_type is not None else cur_row["meal_type"]
        new_mult = float(multiplier) if multiplier is not None else float(cur_row.get("portion_multiplier") or 1.0)
        if not math.isfinite(new_mult) or new_mult < 0.1 or new_mult > 5.0:
            raise FoodGuardrailRejected("implausible_portion", "Pengali porsi harus berada di antara 0.1x hingga 5.0x.")
        new_cap = caption if caption is not None else (cur_row.get("photo_caption") or "")

        cand_totals = totals if totals is not None else {
            "energy_kcal": cur_row["energy_kcal"],
            "protein_g": cur_row["protein_g"],
            "fat_g": cur_row["fat_g"],
            "carb_g": cur_row["carb_g"],
            "fiber_g": cur_row["fiber_g"],
            "sodium_mg": cur_row.get("sodium_mg") or 0.0,
            "sugar_g": cur_row.get("sugar_g") or 0.0,
        }
        new_dish, clean_tot = _validate_meal_nutrients(
            raw_dish,
            cand_totals,
            validate_name=(dish_name is not None),
        )
        row_date = str(cur_row.get("logged_at") or "")[:10] or get_local_now().strftime("%Y-%m-%d")
        _check_daily_meal_budget(
            cur,
            user_id,
            row_date,
            add_kcal=clean_tot["energy_kcal"],
            add_count=1,
            exclude_log_id=log_id,
        )

        cur.execute(
            """
            UPDATE meal_logs
            SET dish_name = ?, energy_kcal = ?, protein_g = ?, fat_g = ?, carb_g = ?, fiber_g = ?,
                sodium_mg = ?, sugar_g = ?, portion_multiplier = ?, photo_caption = ?, meal_type = ?
            WHERE id = ? AND user_id = ?
            """,
            (
                new_dish,
                clean_tot["energy_kcal"],
                clean_tot["protein_g"],
                clean_tot["fat_g"],
                clean_tot["carb_g"],
                clean_tot["fiber_g"],
                clean_tot["sodium_mg"],
                clean_tot["sugar_g"],
                new_mult,
                new_cap,
                new_meal_type,
                log_id,
                user_id,
            ),
        )
        conn.commit()
    return {
        "id": log_id,
        "user_id": user_id,
        "dish_name": new_dish,
        "energy_kcal": clean_tot["energy_kcal"],
        "meal_type": new_meal_type,
        "saved_at": str(cur_row.get("logged_at", ""))[11:16] or get_local_now().strftime("%H:%M"),
    }


def scale_meal_log_portion(log_id: int, user_id: str, new_multiplier: float, new_meal_type: str = None, new_dish_name: str = None):
    """Mengubah porsi dan/atau waktu makan secara proporsional dengan validasi batas harian."""
    try:
        raw_mult = float(new_multiplier)
    except (TypeError, ValueError):
        raise FoodGuardrailRejected("implausible_portion", "Pengali porsi tidak valid.")
    if not math.isfinite(raw_mult) or raw_mult < 0.1 or raw_mult > 5.0:
        raise FoodGuardrailRejected("implausible_portion", "Pengali porsi harus berada di antara 0.1x hingga 5.0x.")

    with _db_session() as (conn, cur):
        row = cur.execute("SELECT * FROM meal_logs WHERE id = ? AND user_id = ?", (log_id, user_id)).fetchone()
        if not row:
            return None
        cur_row = dict(row)

    old_mult = float(cur_row.get("portion_multiplier") or 1.0)
    if old_mult <= 0:
        old_mult = 1.0
    ratio = raw_mult / old_mult

    scaled_totals = {
        "energy_kcal": round(max(0.0, float(cur_row["energy_kcal"])) * ratio, 1),
        "protein_g": round(max(0.0, float(cur_row["protein_g"])) * ratio, 1),
        "fat_g": round(max(0.0, float(cur_row["fat_g"])) * ratio, 1),
        "carb_g": round(max(0.0, float(cur_row["carb_g"])) * ratio, 1),
        "fiber_g": round(max(0.0, float(cur_row["fiber_g"])) * ratio, 1),
        "sodium_mg": round(max(0.0, float(cur_row.get("sodium_mg") or 0.0)) * ratio, 1),
        "sugar_g": round(max(0.0, float(cur_row.get("sugar_g") or 0.0)) * ratio, 1),
    }
    return update_meal_log(
        log_id=log_id,
        user_id=user_id,
        dish_name=new_dish_name,
        totals=scaled_totals,
        multiplier=raw_mult,
        meal_type=new_meal_type,
    )


def find_duplicate_meals(today_meals: list) -> list:
    """Mengidentifikasi entri ganda (nama makanan persis sama >= 2x dalam satu hari)."""
    seen = {}
    dup_ids = []
    # today_meals diurutkan DESC (id terbesar di depan), jadi kemunculan ke-2 dst adalah duplikat lama
    for m in today_meals:
        key = " ".join((m.get("dish_name") or "").strip().lower().split())
        if not key:
            continue
        if key in seen:
            dup_ids.append(m["id"])
        else:
            seen[key] = m["id"]
    return dup_ids


def remove_duplicate_meals_for_date(user_id: str, target_date: str) -> int:
    """Menghapus catatan kembar di satu hari dan menyisakan 1 catatan terbaru per nama menu."""
    with _db_session() as (conn, cur):
        rows = cur.execute(
            """
            SELECT id, dish_name FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ?
            ORDER BY id DESC
            """,
            (user_id, target_date),
        ).fetchall()

        dup_ids = find_duplicate_meals([dict(r) for r in rows])
        for did in dup_ids:
            cur.execute("DELETE FROM meal_logs WHERE id = ? AND user_id = ?", (did, user_id))
        conn.commit()
    return len(dup_ids)


def get_frequent_meals(user_id: str, limit: int = 6) -> list:
    """Mengambil menu makanan yang paling sering dicatat user (dinormalisasi ke porsi 1.0x)."""
    with _db_session() as (conn, cur):
        rows = cur.execute(
            """
            SELECT dish_name,
                   AVG(energy_kcal / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_kcal,
                   AVG(protein_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_p,
                   AVG(fat_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_f,
                   AVG(carb_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_c,
                   AVG(fiber_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_fib,
                    AVG(COALESCE(sodium_mg, 0.0) / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_sod,
                   AVG(COALESCE(sugar_g, 0.0) / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_sug,
                   COUNT(*) AS freq,
                   MAX(id) AS last_id
            FROM meal_logs
            WHERE user_id = ?
            GROUP BY dish_name
            ORDER BY freq DESC, last_id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    results = []
    for r in rows:
        results.append({
            "dish_name": r["dish_name"],
            "freq": int(r["freq"] or 1),
            "energy_kcal": round(float(r["avg_kcal"] or 0.0), 1),
            "protein_g": round(float(r["avg_p"] or 0.0), 1),
            "fat_g": round(float(r["avg_f"] or 0.0), 1),
            "carb_g": round(float(r["avg_c"] or 0.0), 1),
            "fiber_g": round(float(r["avg_fib"] or 0.0), 1),
            "sodium_mg": round(float(r["avg_sod"] or 0.0), 1),
            "sugar_g": round(float(r["avg_sug"] or 0.0), 1),
        })
    return results


def copy_meals_from_date(user_id: str, source_date: str, target_date: str, tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> int:
    """Menyalin daftar menu dari tanggal sumber (mis. kemarin) ke tanggal target secara aman tanpa menduplikasi menu yang sudah ada."""
    if source_date == target_date:
        return 0
    local_now = get_local_now(tz_offset)
    now_hms = local_now.strftime("%H:%M:%S")

    with _db_session() as (conn, cur):
        src_rows = cur.execute(
            """
            SELECT * FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ?
            ORDER BY id ASC
            """,
            (user_id, source_date),
        ).fetchall()
        if not src_rows:
            return 0

        existing_rows = cur.execute(
            """
            SELECT LOWER(TRIM(dish_name)) AS dn, meal_type FROM meal_logs
            WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ?
            """,
            (user_id, target_date),
        ).fetchall()
        existing_keys = {(r["dn"], r["meal_type"]) for r in existing_rows}
        cur_cnt, cur_kcal = _get_daily_meal_usage(cur, user_id, target_date)

        copied = 0
        added_kcal = 0.0
        for r in src_rows:
            if (cur_cnt + copied) >= MAX_DAILY_MEALS_PER_USER:
                break
            d = dict(r)
            row_kcal = float(d.get("energy_kcal") or 0.0)
            if row_kcal < 0 or row_kcal > (MAX_SINGLE_DISH_KCAL * 1.5):
                continue
            if (cur_kcal + added_kcal + row_kcal) > MAX_DAILY_KCAL_PER_USER:
                continue
            key = (" ".join((d["dish_name"] or "").strip().lower().split()), d["meal_type"])
            if key in existing_keys:
                continue
            try:
                clean_dish, clean_tot = _validate_meal_nutrients(d["dish_name"], d, validate_name=True)
            except FoodGuardrailRejected:
                continue
            existing_keys.add(key)
            cur.execute(
                """
                INSERT INTO meal_logs
                (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, sugar_g, portion_multiplier, photo_caption, meal_type, logged_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    clean_dish,
                    clean_tot["energy_kcal"],
                    clean_tot["protein_g"],
                    clean_tot["fat_g"],
                    clean_tot["carb_g"],
                    clean_tot["fiber_g"],
                    clean_tot["sodium_mg"],
                    clean_tot["sugar_g"],
                    min(5.0, max(0.1, float(d.get("portion_multiplier") or 1.0))),
                    d.get("photo_caption") or f"Disalin dari {source_date}",
                    d.get("meal_type") or "Makan Siang",
                    f"{target_date} {now_hms}",
                ),
            )
            copied += 1
            added_kcal += clean_tot["energy_kcal"]
        conn.commit()
    return copied


def delete_meal_log(log_id: int, user_id: str):
    """Menghapus satu catatan makan berdasarkan ID milik user yang sedang aktif."""
    with _db_session() as (conn, cur):
        cur.execute("DELETE FROM meal_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
        conn.commit()
    return True


def _query_stats_and_streak(cur: _UnifiedCursor, user_id: str, target_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> tuple[dict, int]:
    """Menghitung rekapan harian, 7 hari, 30 hari, & streak harian dalam 2 query pada 1 koneksi aktif."""
    local_now = get_local_now(tz_offset)
    local_today = local_now.date()
    if not target_date:
        target_date = local_today.strftime("%Y-%m-%d")

    start_7d = (local_today - timedelta(days=6)).strftime("%Y-%m-%d")
    start_30d = (local_today - timedelta(days=29)).strftime("%Y-%m-%d")
    today_limit = local_today.strftime("%Y-%m-%d")

    date_meals = cur.execute(
        """
        SELECT * FROM meal_logs
        WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) = ?
        ORDER BY id DESC
        """,
        (user_id, target_date),
    ).fetchall()

    daily_rows = cur.execute(
        """
        SELECT SUBSTR(CAST(logged_at AS TEXT), 1, 10) AS day,
               SUM(energy_kcal) AS total_kcal,
               SUM(protein_g) AS total_protein,
               COUNT(*) AS meals_count
        FROM meal_logs
        WHERE user_id = ? AND SUBSTR(CAST(logged_at AS TEXT), 1, 10) <= ?
        GROUP BY SUBSTR(CAST(logged_at AS TEXT), 1, 10)
        ORDER BY day DESC
        """,
        (user_id, today_limit),
    ).fetchall()

    daily_dicts = [dict(r) for r in daily_rows]
    weekly_data = sorted([r for r in daily_dicts if str(r["day"]) >= start_7d], key=lambda x: str(x["day"]))
    monthly_rows = [r for r in daily_dicts if str(r["day"]) >= start_30d]

    logged_dates = set()
    for r in daily_dicts:
        if r.get("day"):
            try:
                logged_dates.add(datetime.strptime(str(r["day"])[:10], "%Y-%m-%d").date())
            except ValueError:
                pass
    cursor_day = local_today if local_today in logged_dates else (local_today - timedelta(days=1))
    streak_days = 0
    while cursor_day in logged_dates:
        streak_days += 1
        cursor_day -= timedelta(days=1)

    meal_dicts = [dict(m) for m in date_meals]
    date_totals = {
        "energy_kcal": round(sum(float(m["energy_kcal"]) for m in meal_dicts), 1),
        "protein_g": round(sum(float(m["protein_g"]) for m in meal_dicts), 1),
        "fat_g": round(sum(float(m["fat_g"]) for m in meal_dicts), 1),
        "carb_g": round(sum(float(m["carb_g"]) for m in meal_dicts), 1),
        "fiber_g": round(sum(float(m["fiber_g"]) for m in meal_dicts), 1),
        "sodium_mg": round(sum(float(m.get("sodium_mg") or 0.0) for m in meal_dicts), 1),
        "sugar_g": round(sum(float(m.get("sugar_g") or 0.0) for m in meal_dicts), 1),
        "count": len(meal_dicts),
        "target_date": target_date
    }

    stats = {
        "today_meals": meal_dicts,
        "today_totals": date_totals,
        "weekly_data": weekly_data,
        "monthly_summary": {
            "total_kcal": round(sum(float(r.get("total_kcal") or 0.0) for r in monthly_rows), 1),
            "active_days": len(monthly_rows),
            "total_meals": sum(int(r.get("meals_count") or 0) for r in monthly_rows)
        }
    }
    return stats, streak_days


def get_user_history_stats(user_id: str, target_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Mengambil rekapan nutrisi harian, mingguan (7 hari), dan bulanan (30 hari)."""
    with _db_session() as (conn, cur):
        stats, _ = _query_stats_and_streak(cur, user_id, target_date=target_date, tz_offset=tz_offset)
    return stats


def get_dashboard_bundle(user_id: str, target_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> dict:
    """Mengambil seluruh data Dashboard dalam 1 koneksi tunggal untuk mempercepat loading Cloud DB."""
    local_now = get_local_now(tz_offset)
    today_str = local_now.strftime("%Y-%m-%d")

    with _db_session() as (conn, cur):
        user_row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        scan_status = _compute_scan_status_from_row(user_row, user_id, tz_offset=tz_offset)
        stats, streak_days = _query_stats_and_streak(cur, user_id, target_date=target_date, tz_offset=tz_offset)

        w_row = cur.execute(
            "SELECT glasses_count, target_glasses FROM water_logs WHERE user_id = ? AND log_date = ?",
            (user_id, today_str),
        ).fetchone()
        rec_water_target = compute_water_target_glasses(
            user_row["weight_kg"] if user_row else 65.0,
            user_row["focus_goal"] if user_row else "Diet Sehat",
        )
        w_glasses = int(w_row[0]) if w_row else 0
        water_data = {
            "glasses": w_glasses,
            "target": rec_water_target,
            "ml": w_glasses * 250,
            "target_ml": rec_water_target * 250,
        }

        wt_rows = cur.execute(
            "SELECT recorded_date, weight_kg, note FROM weight_logs WHERE user_id = ? ORDER BY recorded_date ASC LIMIT 30",
            (user_id,),
        ).fetchall()

        fq_rows = cur.execute(
            """
            SELECT dish_name,
                   AVG(energy_kcal / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_kcal,
                   AVG(protein_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_p,
                   AVG(fat_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_f,
                   AVG(carb_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_c,
                   AVG(fiber_g / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_fib,
                   AVG(COALESCE(sodium_mg, 0.0) / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_sod,
                   AVG(COALESCE(sugar_g, 0.0) / CASE WHEN COALESCE(portion_multiplier, 1.0) > 0 THEN COALESCE(portion_multiplier, 1.0) ELSE 1.0 END) AS avg_sug,
                   COUNT(*) AS freq,
                   MAX(id) AS last_id
            FROM meal_logs
            WHERE user_id = ?
            GROUP BY dish_name
            ORDER BY freq DESC, last_id DESC
            LIMIT 6
            """,
            (user_id,),
        ).fetchall()

    frequent_meals = [{
        "dish_name": r["dish_name"],
        "freq": int(r["freq"] or 1),
        "energy_kcal": round(float(r["avg_kcal"] or 0.0), 1),
        "protein_g": round(float(r["avg_p"] or 0.0), 1),
        "fat_g": round(float(r["avg_f"] or 0.0), 1),
        "carb_g": round(float(r["avg_c"] or 0.0), 1),
        "fiber_g": round(float(r["avg_fib"] or 0.0), 1),
        "sodium_mg": round(float(r["avg_sod"] or 0.0), 1),
        "sugar_g": round(float(r["avg_sug"] or 0.0), 1),
    } for r in fq_rows]

    return {
        "user_row": dict(user_row) if user_row else None,
        "scan_status": scan_status,
        "stats": stats,
        "streak_days": streak_days,
        "water_data": water_data,
        "weight_history": [dict(r) for r in wt_rows],
        "frequent_meals": frequent_meals,
    }


def export_user_data_json(user_id: str) -> str:
    """Mengekspor data profil, preferensi, dan seluruh riwayat catatan makan pengguna ke format JSON."""
    import json
    with _db_session() as (conn, cur):
        user_row = cur.execute(
            "SELECT user_id, display_name, daily_calorie_target, theme_preference, gender, weight_kg, height_cm, age_years, subscription_tier, timezone_offset, focus_goal, fasting_mode, created_at FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        meal_rows = cur.execute(
            "SELECT dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, sugar_g, portion_multiplier, photo_caption, meal_type, logged_at FROM meal_logs WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        custom_rows = cur.execute(
            "SELECT food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g FROM custom_foods WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        weight_rows = cur.execute(
            "SELECT recorded_date, weight_kg, note FROM weight_logs WHERE user_id = ? ORDER BY recorded_date ASC",
            (user_id,),
        ).fetchall()

    data = {
        "backup_version": "2.0",
        "exported_at": get_local_now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_profile": dict(user_row) if user_row else {"user_id": user_id},
        "meal_logs": [dict(m) for m in meal_rows],
        "custom_foods": [dict(c) for c in custom_rows],
        "weight_logs": [dict(w) for w in weight_rows]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


def _safe_float(val, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        parsed = float(val)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _normalize_backup_timestamp(raw_val, fallback: str) -> str | None:
    raw = str(raw_val or "").strip()
    if not raw:
        return fallback
    if len(raw) >= 19:
        try:
            dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    if len(raw) >= 10:
        try:
            dt = datetime.strptime(raw[:10], "%Y-%m-%d")
            return dt.strftime("%Y-%m-%d 12:00:00")
        except ValueError:
            return None
    return None


def import_user_data_json(user_id: str, json_str: str) -> tuple[bool, str]:
    """Memulihkan riwayat catatan makan, berat badan, & makanan kustom dari JSON dengan validasi guardrail ketat."""
    import json
    try:
        clean_raw = (json_str or "").lstrip("\ufeff").strip()
        data = json.loads(clean_raw)
        if not isinstance(data, dict):
            return False, "Format file cadangan harus berupa objek JSON yang valid."

        meal_logs = data.get("meal_logs") or []
        weight_logs = data.get("weight_logs") or []
        custom_foods = data.get("custom_foods") or []
        if not meal_logs and not weight_logs and not custom_foods:
            return False, "File cadangan tidak memuat catatan makanan, berat badan, atau makanan kustom."

        norm_uid = _normalize_user_id(user_id)
        now_fallback = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
        skipped_invalid = 0

        with _db_session() as (conn, cur):
            day_usage_cache: dict[str, list[float | int]] = {}
            imported_count = 0
            for m in meal_logs:
                if not isinstance(m, dict):
                    skipped_invalid += 1
                    continue
                logged_val = _normalize_backup_timestamp(m.get("logged_at"), now_fallback)
                if not logged_val:
                    skipped_invalid += 1
                    continue
                try:
                    clean_dish, clean_tot = _validate_meal_nutrients(
                        m.get("dish_name"),
                        m,
                        validate_name=True,
                        check_macro_atwater=True,
                        raw_item=m,
                    )
                except FoodGuardrailRejected:
                    skipped_invalid += 1
                    continue

                day_key = logged_val[:10]
                if day_key not in day_usage_cache:
                    c_cnt, c_kcal = _get_daily_meal_usage(cur, norm_uid, day_key)
                    day_usage_cache[day_key] = [c_cnt, c_kcal]
                d_cnt, d_kcal = day_usage_cache[day_key]
                if d_cnt >= MAX_DAILY_MEALS_PER_USER or (d_kcal + clean_tot["energy_kcal"]) > MAX_DAILY_KCAL_PER_USER:
                    skipped_invalid += 1
                    continue

                existing = cur.execute(
                    "SELECT id FROM meal_logs WHERE user_id = ? AND dish_name = ? AND logged_at = ?",
                    (norm_uid, clean_dish, logged_val),
                ).fetchone()
                if not existing:
                    port_mult = _safe_float(m.get("portion_multiplier"), 1.0)
                    if port_mult < 0.1 or port_mult > 5.0:
                        port_mult = 1.0
                    cur.execute(
                        """
                        INSERT INTO meal_logs
                        (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, sugar_g, portion_multiplier, photo_caption, meal_type, logged_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            norm_uid,
                            clean_dish,
                            clean_tot["energy_kcal"],
                            clean_tot["protein_g"],
                            clean_tot["fat_g"],
                            clean_tot["carb_g"],
                            clean_tot["fiber_g"],
                            clean_tot["sodium_mg"],
                            clean_tot["sugar_g"],
                            port_mult,
                            str(m.get("photo_caption") or "")[:160],
                            str(m.get("meal_type") or "Makan Siang")[:40],
                            logged_val,
                        ),
                    )
                    day_usage_cache[day_key][0] += 1
                    day_usage_cache[day_key][1] += clean_tot["energy_kcal"]
                    imported_count += 1

            weight_count = 0
            for w in weight_logs:
                if not isinstance(w, dict):
                    skipped_invalid += 1
                    continue
                rec_date_raw = str(w.get("recorded_date") or "").strip()
                try:
                    rec_date = datetime.strptime(rec_date_raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
                    w_kg = round(float(w.get("weight_kg")), 1)
                except (TypeError, ValueError):
                    skipped_invalid += 1
                    continue
                if not math.isfinite(w_kg) or w_kg < 20.0 or w_kg > 300.0:
                    skipped_invalid += 1
                    continue
                cur.execute(
                    """
                    INSERT INTO weight_logs (user_id, weight_kg, recorded_date, note)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, recorded_date) DO NOTHING
                    """,
                    (norm_uid, w_kg, rec_date, str(w.get("note") or "")[:120]),
                )
                weight_count += 1

            custom_count = 0
            for cf in custom_foods:
                if not isinstance(cf, dict):
                    skipped_invalid += 1
                    continue
                try:
                    clean_cf, clean_cf_tot = _validate_meal_nutrients(
                        cf.get("food_name"),
                        cf,
                        validate_name=True,
                        check_macro_atwater=True,
                        raw_item=cf,
                    )
                except FoodGuardrailRejected:
                    skipped_invalid += 1
                    continue
                ex_cf = cur.execute(
                    "SELECT id FROM custom_foods WHERE user_id = ? AND LOWER(food_name) = LOWER(?) LIMIT 1",
                    (norm_uid, clean_cf),
                ).fetchone()
                if not ex_cf:
                    cur.execute(
                        """
                        INSERT INTO custom_foods (user_id, food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            norm_uid,
                            clean_cf,
                            str(cf.get("serving_size") or "1 porsi")[:50],
                            clean_cf_tot["energy_kcal"],
                            clean_cf_tot["protein_g"],
                            clean_cf_tot["fat_g"],
                            clean_cf_tot["carb_g"],
                            now_fallback,
                        ),
                    )
                    custom_count += 1

            conn.commit()
        if imported_count == 0 and weight_count == 0 and custom_count == 0 and skipped_invalid > 0:
            return False, "Pemulihan ditolak: seluruh entri cadangan tidak lolos validasi keamanan & kewajaran gizi."
        skip_note = f" ({skipped_invalid} entri tidak valid dilewati)" if skipped_invalid > 0 else ""
        return True, f"Berhasil memulihkan {imported_count} catatan makan, {weight_count} berat badan, & {custom_count} menu kustom!{skip_note}"
    except Exception as e:
        return False, f"Format file cadangan tidak valid: {str(e)}"


def stage_pending_food(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi (100g)", serving_weight: float = 100.0, source_origin: str = "Open Food Facts", submitted_by: str = "system"):
    """Menyimpan data pangan baru yang lolos guardrail ke tabel antrean (pending_foods) agar dapat ditinjau sebelum publikasi."""
    if not submitted_by or is_guest_user_id(submitted_by):
        return None
    try:
        clean_name = validate_food_candidate(
            food_name=food_name,
            energy_kcal=kcal_100,
            protein_g=p_100,
            fat_g=f_100,
            carb_g=c_100,
            fiber_g=fib_100,
            is_catalog_entry=True,
        )
    except FoodGuardrailRejected:
        return None
    if not clean_name or kcal_100 < 0:
        return None

    # Cek duplikasi barcode di katalog lokal TKPI
    if barcode and os.path.exists(DB_PATH):
        sq = sqlite3.connect(DB_PATH)
        ex_main = sq.execute("SELECT id FROM food_composition WHERE barcode = ?", (barcode.strip(),)).fetchone()
        sq.close()
        if ex_main:
            return None

    now_str = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
    with _db_session() as (conn, cur):
        if barcode:
            ex_pend = cur.execute("SELECT id FROM pending_foods WHERE barcode = ? AND status = 'pending'", (barcode.strip(),)).fetchone()
            if ex_pend:
                return None
        ex_name = cur.execute("SELECT id FROM pending_foods WHERE LOWER(food_name) = LOWER(?) AND status = 'pending'", (clean_name,)).fetchone()
        if ex_name:
            return ex_name[0]

        cur.execute(
            """
            INSERT INTO pending_foods
            (food_name, category, serving_unit, default_serving_weight, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode, source_origin, submitted_by, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (
                clean_name, category, serving_unit, float(serving_weight),
                round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
                round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
                barcode.strip() if barcode else None, source_origin, submitted_by, now_str,
            ),
        )
        new_id = cur.lastrowid
        conn.commit()
    return new_id


def get_pending_foods(status: str = "pending"):
    """Mengambil daftar pangan yang menunggu kurasi/edit sebelum publikasi."""
    with _db_session() as (conn, cur):
        rows = cur.execute("SELECT * FROM pending_foods WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
        return [dict(r) for r in rows]


def publish_food_to_catalog(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi", serving_weight: float = 100.0, pending_id: int = None):
    """
    Mempublikasikan data pangan yang sudah diverifikasi ke katalog lokal (food_composition)
    sekaligus menyimpannya permanen ke cloud (food_catalog_additions) bila Supabase aktif.
    """
    clean_name = validate_food_candidate(
        food_name=food_name,
        energy_kcal=kcal_100,
        protein_g=p_100,
        fat_g=f_100,
        carb_g=c_100,
        fiber_g=fib_100,
        is_catalog_entry=True,
    )
    clean_barcode = barcode.strip() if barcode else None
    code_hash = hashlib.md5(clean_name.lower().encode("utf-8")).hexdigest()[:8].upper()
    food_code = f"MN_{code_hash}"
    now_str = get_local_now().strftime("%Y-%m-%d %H:%M:%S")

    # 1. Selalu perbarui katalog lokal TKPI SQLite (tempat find_best_match mencari)
    sq = sqlite3.connect(DB_PATH)
    sq.row_factory = sqlite3.Row
    sq_cur = sq.cursor()
    existing = None
    if clean_barcode:
        existing = sq_cur.execute("SELECT id FROM food_composition WHERE barcode = ? LIMIT 1", (clean_barcode,)).fetchone()
    if not existing:
        existing = sq_cur.execute("SELECT id FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1", (clean_name,)).fetchone()

    if existing:
        sq_cur.execute(
            """
            UPDATE food_composition
            SET food_name = ?, category = ?, serving_unit = ?, default_serving_weight = ?,
                energy_kcal = ?, protein_g = ?, fat_g = ?, carb_g = ?, fiber_g = ?, sodium_mg = ?,
                barcode = COALESCE(?, barcode)
            WHERE id = ?
            """,
            (
                clean_name, category, serving_unit, float(serving_weight),
                round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
                round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
                clean_barcode, existing["id"],
            ),
        )
    else:
        sq_cur.execute(
            """
            INSERT INTO food_composition
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode)
            VALUES (?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                food_code, clean_name, category, serving_unit, float(serving_weight),
                round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
                round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
                clean_barcode,
            ),
        )
    sq.commit()
    sq.close()
    try:
        from nutrition_engine import invalidate_food_catalog_cache
        invalidate_food_catalog_cache()
    except Exception:
        pass

    # 2. Perbarui status draft & simpan ke katalog cloud permanen
    with _db_session() as (conn, cur):
        if conn.backend == "postgres":
            existing_cloud = cur.execute(
                "SELECT id, food_code FROM food_catalog_additions WHERE LOWER(food_name) = LOWER(?) LIMIT 1",
                (clean_name,),
            ).fetchone()
            if existing_cloud:
                cur.execute(
                    """
                    UPDATE food_catalog_additions
                    SET food_name = ?, category = ?, serving_unit = ?, default_serving_weight = ?,
                        energy_kcal = ?, protein_g = ?, fat_g = ?, carb_g = ?, fiber_g = ?, sodium_mg = ?,
                        barcode = COALESCE(?, barcode), updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        clean_name, category, serving_unit, float(serving_weight),
                        round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
                        round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
                        clean_barcode, now_str, existing_cloud["id"],
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO food_catalog_additions
                    (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode, updated_at)
                    VALUES (?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (food_code) DO UPDATE SET
                        food_name = excluded.food_name,
                        category = excluded.category,
                        serving_unit = excluded.serving_unit,
                        default_serving_weight = excluded.default_serving_weight,
                        energy_kcal = excluded.energy_kcal,
                        protein_g = excluded.protein_g,
                        fat_g = excluded.fat_g,
                        carb_g = excluded.carb_g,
                        fiber_g = excluded.fiber_g,
                        sodium_mg = excluded.sodium_mg,
                        barcode = COALESCE(excluded.barcode, food_catalog_additions.barcode),
                        updated_at = excluded.updated_at
                    """,
                    (
                        food_code, clean_name, category, serving_unit, float(serving_weight),
                        round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
                        round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
                        clean_barcode, now_str,
                    ),
                )
        if pending_id is not None:
            cur.execute("UPDATE pending_foods SET status = 'published' WHERE id = ?", (pending_id,))
        conn.commit()
    return True


def reject_pending_food(pending_id: int):
    """Menolak/menghapus item dari antrean draft."""
    with _db_session() as (conn, cur):
        cur.execute("UPDATE pending_foods SET status = 'rejected' WHERE id = ?", (pending_id,))
        conn.commit()
    return True


if __name__ == "__main__":
    init_user_history_tables()
    print("Tabel Nutrisi Cerdas siap!", get_storage_backend_info())

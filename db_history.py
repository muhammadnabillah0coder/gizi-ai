"""
Database History & Multi-User Manager (Gizi.AI)
Mengelola profil pengguna (termasuk email/Google Account) dan riwayat log makanan harian.
"""

import sqlite3
import os
import hmac
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

# Mode Rilis Open Beta: QRIS ditutup sementara, teman terdaftar mendapat 5x scan foto AI/hari
OPEN_BETA_MODE = True
BETA_DAILY_SCAN_LIMIT = 5
GUEST_DAILY_SCAN_LIMIT = 3
DEFAULT_TIMEZONE_OFFSET = 8  # WITA (Tanah Grogot / Kaltim)

ADMIN_IDENTIFIERS = {
    "nabillah",
    "muhammadnabillah0coder@gmail.com",
    "pkm tanah grogot",
    "admin"
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

    # Fallback lokal (mis. unit test / offline): simpan secret acak per instance DB di app_meta
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS app_meta (meta_key TEXT PRIMARY KEY, meta_value TEXT NOT NULL)")
    row = cur.execute("SELECT meta_value FROM app_meta WHERE meta_key = 'session_hmac_secret'").fetchone()
    if row and row[0]:
        secret_hex = row[0]
    else:
        secret_hex = secrets.token_hex(32)
        cur.execute("INSERT OR REPLACE INTO app_meta (meta_key, meta_value) VALUES ('session_hmac_secret', ?)", (secret_hex,))
        conn.commit()
    conn.close()
    return secret_hex.encode("utf-8")

def create_session_token(user_id: str) -> str:
    """Membuat token HMAC bertanda tangan agar ?u= hanya valid untuk pengguna yang sudah login."""
    clean_id = (user_id or "").strip().lower()
    if not clean_id or clean_id == "tamu (demo)":
        return ""
    key = _get_session_secret_key()
    return hmac.new(key, clean_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

def verify_session_token(user_id: str, token: str) -> bool:
    """Memvalidasi token HMAC URL menggunakan perbandingan constant-time."""
    clean_id = (user_id or "").strip().lower()
    if not clean_id or not token or clean_id == "tamu (demo)":
        return False
    expected = create_session_token(clean_id)
    return hmac.compare_digest(expected, str(token).strip())

def init_user_history_tables():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Tabel Pengguna (Mendukung Email, Username, Password/PIN Terenkripsi)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,      -- Email unik atau nomor WA/ID pengguna
            display_name TEXT,
            password_hash TEXT,                -- PIN/Password aman
            avatar_url TEXT,
            auth_provider TEXT DEFAULT 'local', -- 'google', 'local', atau 'whatsapp'
            theme_preference TEXT DEFAULT 'Apple Light',
            daily_calorie_target REAL DEFAULT 2000.0,
            gender TEXT DEFAULT 'Pria',
            weight_kg REAL DEFAULT 65.0,
            height_cm REAL DEFAULT 170.0,
            age_years INTEGER DEFAULT 25,
            subscription_tier TEXT DEFAULT 'free',
            pro_until TIMESTAMP,
            daily_scans_count INTEGER DEFAULT 0,
            last_scan_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migrasi kolom password_hash jika belum ada
    try:
        cur.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN gender TEXT DEFAULT 'Pria'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN weight_kg REAL DEFAULT 65.0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN height_cm REAL DEFAULT 170.0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN age_years INTEGER DEFAULT 25")
    except:
        pass
    # Migrasi kolom theme_preference jika belum ada
    try:
        cur.execute("ALTER TABLE users ADD COLUMN theme_preference TEXT DEFAULT 'Apple Light'")
    except:
        pass
        
    # Migrasi kolom subscription_tier, scan quota, zona waktu, dan fokus klinis
    for alter_sql in [
        "ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'beta'",
        "ALTER TABLE users ADD COLUMN pro_until TIMESTAMP",
        "ALTER TABLE users ADD COLUMN daily_scans_count INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN last_scan_date TEXT",
        "ALTER TABLE users ADD COLUMN timezone_offset INTEGER DEFAULT 8",
        "ALTER TABLE users ADD COLUMN focus_goal TEXT DEFAULT 'Diet Sehat'",
    ]:
        try:
            cur.execute(alter_sql)
        except Exception:
            pass
    
    # Tabel Log Makanan (Mendukung Kategori Waktu Makan & Natrium)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS meal_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            dish_name TEXT NOT NULL,
            energy_kcal REAL NOT NULL,
            protein_g REAL NOT NULL,
            fat_g REAL NOT NULL,
            carb_g REAL NOT NULL,
            fiber_g REAL NOT NULL,
            sodium_mg REAL DEFAULT 0.0,
            portion_multiplier REAL DEFAULT 1.0,
            photo_caption TEXT,
            meal_type TEXT DEFAULT 'Makan Siang', -- 'Sarapan', 'Makan Siang', 'Makan Malam', 'Camilan'
            logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for meal_alter in [
        "ALTER TABLE meal_logs ADD COLUMN meal_type TEXT DEFAULT 'Makan Siang'",
        "ALTER TABLE meal_logs ADD COLUMN sodium_mg REAL DEFAULT 0.0",
    ]:
        try:
            cur.execute(meal_alter)
        except Exception:
            pass
        
    # Tabel Log Asupan Air Harian (Water Intake Tracker)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS water_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            log_date TEXT NOT NULL,
            glasses_count INTEGER DEFAULT 0,
            target_glasses INTEGER DEFAULT 8,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, log_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_water_user_date ON water_logs(user_id, log_date)")

    # Tabel Pelacak Berat Badan (Weight Tracker)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS weight_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            weight_kg REAL NOT NULL,
            recorded_date TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, recorded_date)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_weight_user_date ON weight_logs(user_id, recorded_date)")
    # Tabel Makanan Kustom Pribadi (Fitur Input Manual User)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            food_name TEXT NOT NULL,
            serving_size TEXT DEFAULT '1 porsi',
            energy_kcal REAL NOT NULL,
            protein_g REAL DEFAULT 0.0,
            fat_g REAL DEFAULT 0.0,
            carb_g REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_custom_food_user ON custom_foods(user_id)")
    
    # Tabel Antrean Moderasi / Staging Pangan Baru (Edit Sebelum Publikasi)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pending_foods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            food_name TEXT NOT NULL,
            category TEXT DEFAULT 'Produk Kemasan / Ritel',
            serving_unit TEXT DEFAULT '1 porsi (100g)',
            default_serving_weight REAL DEFAULT 100.0,
            energy_kcal REAL NOT NULL,
            protein_g REAL DEFAULT 0.0,
            fat_g REAL DEFAULT 0.0,
            carb_g REAL DEFAULT 0.0,
            fiber_g REAL DEFAULT 0.0,
            sodium_mg REAL DEFAULT 0.0,
            barcode TEXT,
            source_origin TEXT DEFAULT 'Open Food Facts / AI',
            submitted_by TEXT DEFAULT 'system',
            status TEXT DEFAULT 'pending', -- 'pending', 'published', 'rejected'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()

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
        return True, False
    clean_pw = (input_password or "").strip()
    if saved_hash.startswith("pbkdf2$"):
        parts = saved_hash.split("$")
        if len(parts) != 3:
            return False, False
        _, salt_hex, expected_hex = parts
        candidate = hash_password(clean_pw, salt_hex=salt_hex)
        return hmac.compare_digest(candidate, saved_hash), False

    # Kompatibilitas mundur hash SHA-256 lama (otomatis di-upgrade saat login berhasil)
    legacy_hex = hashlib.sha256(clean_pw.encode("utf-8")).hexdigest()
    is_valid = hmac.compare_digest(legacy_hex, saved_hash)
    return is_valid, is_valid

def register_user(user_id: str, display_name: str, pin_or_pass: str, gender: str = "Pria", bb: float = 65.0, tb: float = 170.0, age: int = 25, target_kcal: float = 2000.0, focus_goal: str = "Diet Sehat", timezone_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """
    Mendaftarkan akun baru dengan verifikasi PIN/Password aman PBKDF2 dan profil tubuh pribadi.
    """
    clean_id = (user_id or "").strip().lower()
    if not clean_id or clean_id == "tamu (demo)":
        return False, "ID Pengguna / Email tidak valid atau kosong."
    if not pin_or_pass or len(pin_or_pass.strip()) < 4:
        return False, "PIN / Password minimal 4 karakter agar akun Anda aman."
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # Cek apakah ID sudah dipakai
    existing = cur.execute("SELECT id FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    if existing:
        conn.close()
        return False, "ID Pengguna / Email ini sudah terdaftar. Silakan login."
        
    p_hash = hash_password(pin_or_pass)
    is_admin = is_admin_user(clean_id)
    if is_admin:
        initial_tier = "pro"
        initial_expiry = "2099-12-31 23:59:59"
    else:
        initial_tier = "beta" if OPEN_BETA_MODE else "free"
        initial_expiry = None
        
    local_now = get_local_now(timezone_offset)
    
    cur.execute("""
        INSERT INTO users 
        (user_id, display_name, password_hash, auth_provider, daily_calorie_target, gender, weight_kg, height_cm, age_years, subscription_tier, pro_until, timezone_offset, focus_goal, created_at)
        VALUES (?, ?, ?, 'local', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (clean_id, (display_name or clean_id.split("@")[0].capitalize()).strip(), p_hash, target_kcal, gender, bb, tb, age, initial_tier, initial_expiry, int(timezone_offset), focus_goal, local_now.strftime("%Y-%m-%d %H:%M:%S")))

    if bb and float(bb) > 0:
        cur.execute("""
            INSERT OR REPLACE INTO weight_logs (user_id, weight_kg, recorded_date, note, created_at)
            VALUES (?, ?, ?, 'Berat awal pendaftaran', ?)
        """, (clean_id, round(float(bb), 1), local_now.strftime("%Y-%m-%d"), local_now.strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    row = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    user_dict = dict(row)
    conn.close()
    return True, user_dict

def authenticate_user(user_id: str, pin_or_pass: str):
    """
    Memverifikasi login pengguna dengan ID dan PIN/Password (otomatis upgrade hash lama ke PBKDF2).
    """
    clean_id = (user_id or "").strip().lower()
    if not clean_id:
        return False, "Ketikkan ID Pengguna / Email Anda."
        
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    user = cur.execute("SELECT * FROM users WHERE LOWER(user_id) = ?", (clean_id,)).fetchone()
    if not user:
        conn.close()
        return False, "Akun tidak ditemukan. Silakan klik 'Daftar Akun Baru'."
        
    u_dict = dict(user)
    saved_hash = u_dict.get("password_hash")
    
    if saved_hash:
        valid, needs_upgrade = _verify_password(pin_or_pass, saved_hash)
        if not valid:
            conn.close()
            return False, "PIN / Password salah! Silakan periksa kembali."
        if needs_upgrade:
            new_hash = hash_password(pin_or_pass)
            cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, u_dict["id"]))
            conn.commit()
            u_dict["password_hash"] = new_hash
            
    conn.close()
    return True, u_dict

def is_admin_user(user_id: str) -> bool:
    """Mengecek secara ketat (exact match) apakah user adalah Founder / Admin aplikasi."""
    if not user_id:
        return False
    uid = user_id.strip().lower()
    return uid in ADMIN_IDENTIFIERS

def get_or_create_user(user_id: str, display_name: str = "", auth_provider: str = "local"):
    """
    Mengambil data user atau membuat profil baru jika belum ada.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    is_admin = is_admin_user(user_id)
    initial_tier = "pro" if is_admin else ("beta" if (OPEN_BETA_MODE and user_id != "Tamu (Demo)") else "free")
    initial_expiry = "2099-12-31 23:59:59" if is_admin else None
    
    row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        name = display_name or user_id.split("@")[0].capitalize()
        cur.execute("""
            INSERT INTO users (user_id, display_name, auth_provider, daily_calorie_target, subscription_tier, pro_until, timezone_offset, focus_goal)
            VALUES (?, ?, ?, 2000.0, ?, ?, ?, 'Diet Sehat')
        """, (user_id, name, auth_provider, initial_tier, initial_expiry, DEFAULT_TIMEZONE_OFFSET))
        conn.commit()
        row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    else:
        if is_admin and row["subscription_tier"] != "pro":
            cur.execute("UPDATE users SET subscription_tier = 'pro', pro_until = '2099-12-31 23:59:59' WHERE user_id = ?", (user_id,))
            conn.commit()
            row = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        
    user_dict = dict(row)
    conn.close()
    return user_dict

def add_custom_food(user_id: str, food_name: str, serving_size: str, kcal: float, protein: float, fat: float, carb: float):
    """Menyimpan makanan manual buatan pengguna sendiri."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO custom_foods (user_id, food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, food_name, serving_size, kcal, protein, fat, carb))
    conn.commit()
    conn.close()
    return True

def get_custom_foods(user_id: str):
    """Mengambil daftar makanan kustom yang pernah disimpan pengguna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM custom_foods WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_custom_food(food_id: int, user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM custom_foods WHERE id = ? AND user_id = ?", (food_id, user_id))
    conn.commit()
    conn.close()
    return True

def update_calorie_target(user_id: str, target_kcal: float):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET daily_calorie_target = ? WHERE user_id = ?", (target_kcal, user_id))
    conn.commit()
    conn.close()

def update_user_theme(user_id: str, theme_name: str):
    """Menyimpan tema pilihan pengguna ke database permanen."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET theme_preference = ? WHERE user_id = ?", (theme_name, user_id))
    conn.commit()
    conn.close()

def update_user_preferences(user_id: str, timezone_offset: int = None, focus_goal: str = None):
    """Memperbarui preferensi zona waktu (WIB/WITA/WIT) dan fokus kesehatan pengguna."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    if timezone_offset is not None:
        cur.execute("UPDATE users SET timezone_offset = ? WHERE user_id = ?", (int(timezone_offset), user_id))
    if focus_goal is not None:
        cur.execute("UPDATE users SET focus_goal = ? WHERE user_id = ?", (focus_goal.strip(), user_id))
    conn.commit()
    conn.close()
    return True

def log_weight_entry(user_id: str, weight_kg: float, note: str = "", tz_offset: int = DEFAULT_TIMEZONE_OFFSET, recorded_date: str = None):
    """Mencatat atau memperbarui berat badan harian ke tabel weight_logs sekaligus sinkron profil user."""
    clean_w = round(float(weight_kg), 1)
    if clean_w <= 0:
        return False
    local_now = get_local_now(tz_offset)
    r_date = recorded_date or local_now.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO weight_logs (user_id, weight_kg, recorded_date, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, recorded_date) DO UPDATE SET
            weight_kg = excluded.weight_kg,
            note = excluded.note,
            created_at = excluded.created_at
    """, (user_id, clean_w, r_date, note or "", local_now.strftime("%Y-%m-%d %H:%M:%S")))
    cur.execute("UPDATE users SET weight_kg = ? WHERE user_id = ?", (clean_w, user_id))
    conn.commit()
    conn.close()
    return True

def get_weight_history(user_id: str, limit: int = 30):
    """Mengambil histori berat badan pengguna secara kronologis untuk grafik progres."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT recorded_date, weight_kg, note
        FROM weight_logs
        WHERE user_id = ?
        ORDER BY recorded_date ASC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_logging_streak(user_id: str, tz_offset: int = DEFAULT_TIMEZONE_OFFSET) -> int:
    """Menghitung jumlah hari berturut-turut (streak) pengguna mencatat makanan."""
    local_today = get_local_now(tz_offset).date()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT DISTINCT date(logged_at) as d
        FROM meal_logs
        WHERE user_id = ? AND date(logged_at) <= ?
        ORDER BY d DESC
    """, (user_id, local_today.strftime("%Y-%m-%d"))).fetchall()
    conn.close()

    if not rows:
        return 0

    logged_dates = {datetime.strptime(r[0], "%Y-%m-%d").date() for r in rows if r[0]}
    # Jika hari ini belum sempat catat (mis. baru bangun pagi), lanjut hitung mulai kemarin
    cursor_day = local_today if local_today in logged_dates else (local_today - timedelta(days=1))
    streak = 0
    while cursor_day in logged_dates:
        streak += 1
        cursor_day -= timedelta(days=1)
    return streak

def log_water_intake(user_id: str, delta_glasses: int = 1, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Menambah atau mengurangi asupan air minum hari ini (+1 atau -1 gelas)."""
    local_now = get_local_now(tz_offset)
    today_str = local_now.strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    cur.execute("SELECT glasses_count FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str))
    row = cur.fetchone()
    if row:
        new_count = max(0, row[0] + delta_glasses)
        cur.execute("UPDATE water_logs SET glasses_count = ?, updated_at = ? WHERE user_id = ? AND log_date = ?", (new_count, local_now.strftime("%Y-%m-%d %H:%M:%S"), user_id, today_str))
    else:
        new_count = max(0, delta_glasses)
        cur.execute("INSERT INTO water_logs (user_id, log_date, glasses_count, target_glasses, updated_at) VALUES (?, ?, ?, 8, ?)", (user_id, today_str, new_count, local_now.strftime("%Y-%m-%d %H:%M:%S")))
        
    conn.commit()
    conn.close()
    return new_count

def get_water_intake(user_id: str, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """Mengambil progres air minum hari ini."""
    today_str = get_local_now(tz_offset).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT glasses_count, target_glasses FROM water_logs WHERE user_id = ? AND log_date = ?", (user_id, today_str))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"glasses": row[0], "target": row[1], "ml": row[0] * 250, "target_ml": row[1] * 250}
    return {"glasses": 0, "target": 8, "ml": 0, "target_ml": 2000}

def get_user_scan_status(user_id: str, tz_offset: int = None):
    """
    Memeriksa kuota scan foto harian user:
    - Admin: Unlimited
    - Open Beta (akun terdaftar): 5x scan foto/hari (3x makan berat + 2x jajan)
    - Tamu (Demo): 3x scan foto/hari
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    user = cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    
    effective_tz = tz_offset if tz_offset is not None else (user["timezone_offset"] if user and "timezone_offset" in user.keys() and user["timezone_offset"] is not None else DEFAULT_TIMEZONE_OFFSET)
    local_now = get_local_now(effective_tz)

    if not user:
        return {"tier": "demo", "scans_today": 0, "max_scans": GUEST_DAILY_SCAN_LIMIT, "can_scan": True, "is_pro": False, "is_beta": False, "days_left": 0}
        
    u_dict = dict(user)
    is_admin = is_admin_user(user_id)
    is_guest = (user_id == "Tamu (Demo)")
    tier = u_dict.get("subscription_tier") or ("demo" if is_guest else "beta")
    pro_until_str = u_dict.get("pro_until")
    
    is_pro = False
    is_beta = OPEN_BETA_MODE and not is_guest and not is_admin
    days_left = 0
    if is_admin:
        is_pro = True
        tier = "pro"
        days_left = 9999
        max_scans = 9999
    elif OPEN_BETA_MODE:
        if is_guest:
            tier = "demo"
            max_scans = GUEST_DAILY_SCAN_LIMIT
        else:
            tier = "beta"
            max_scans = BETA_DAILY_SCAN_LIMIT
    else:
        if tier == "pro" and pro_until_str:
            try:
                expiry_dt = datetime.strptime(pro_until_str, "%Y-%m-%d %H:%M:%S")
                if expiry_dt > local_now:
                    is_pro = True
                    days_left = max(1, (expiry_dt - local_now).days)
                else:
                    is_pro = False
                    tier = "free"
            except Exception:
                is_pro = True
        max_scans = 9999 if is_pro else GUEST_DAILY_SCAN_LIMIT
            
    today_str = local_now.strftime("%Y-%m-%d")
    last_date = u_dict.get("last_scan_date")
    scans_today = u_dict.get("daily_scans_count") or 0
    
    if last_date != today_str:
        scans_today = 0
        
    can_scan = True if (is_admin or (is_pro and not OPEN_BETA_MODE)) else (scans_today < max_scans)
    
    return {
        "tier": tier,
        "scans_today": scans_today,
        "max_scans": max_scans,
        "can_scan": can_scan,
        "is_pro": is_pro,
        "is_beta": is_beta,
        "days_left": days_left
    }

def record_scan_usage(user_id: str, tz_offset: int = None):
    """Mencatat 1 kali pemakaian scan foto makanan pada tanggal lokal pengguna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    row = cur.execute("SELECT last_scan_date, daily_scans_count, timezone_offset FROM users WHERE user_id = ?", (user_id,)).fetchone()
    
    effective_tz = tz_offset if tz_offset is not None else (row["timezone_offset"] if row and row["timezone_offset"] is not None else DEFAULT_TIMEZONE_OFFSET)
    today_str = get_local_now(effective_tz).strftime("%Y-%m-%d")
    
    if row:
        last_date, count = row["last_scan_date"], row["daily_scans_count"] or 0
        new_count = 1 if last_date != today_str else count + 1
        cur.execute("UPDATE users SET last_scan_date = ?, daily_scans_count = ? WHERE user_id = ?", (today_str, new_count, user_id))
    conn.commit()
    conn.close()

def activate_pro_tier(user_id: str, days: int = 30):
    """Mengaktifkan langganan Pro untuk pengguna."""
    expiry = (get_local_now(DEFAULT_TIMEZONE_OFFSET) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE users SET subscription_tier = 'pro', pro_until = ? WHERE user_id = ?", (expiry, user_id))
    conn.commit()
    conn.close()
    return expiry

def log_meal(user_id: str, dish_name: str, totals: dict, multiplier: float = 1.0, caption: str = "", meal_type: str = "Makan Siang", log_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """
    Menyimpan satu catatan makan ke buku harian pengguna dengan waktu lokal Indonesia yang akurat.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    local_now = get_local_now(tz_offset)
    target_d = log_date or local_now.strftime("%Y-%m-%d")
    custom_timestamp = f"{target_d} {local_now.strftime('%H:%M:%S')}"
    
    cur.execute("""
        INSERT INTO meal_logs 
        (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, portion_multiplier, photo_caption, meal_type, logged_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        dish_name,
        totals.get("energy_kcal", 0.0),
        totals.get("protein_g", 0.0),
        totals.get("fat_g", 0.0),
        totals.get("carb_g", 0.0),
        totals.get("fiber_g", 0.0),
        totals.get("sodium_mg", 0.0),
        multiplier,
        caption,
        meal_type,
        custom_timestamp
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "user_id": user_id,
        "dish_name": dish_name,
        "energy_kcal": totals.get("energy_kcal", 0.0),
        "meal_type": meal_type,
        "saved_at": local_now.strftime("%H:%M")
    }

def delete_meal_log(log_id: int, user_id: str):
    """
    Menghapus satu catatan makan berdasarkan ID milik user yang sedang aktif.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM meal_logs WHERE id = ? AND user_id = ?", (log_id, user_id))
    conn.commit()
    conn.close()
    return True

def get_user_history_stats(user_id: str, target_date: str = None, tz_offset: int = DEFAULT_TIMEZONE_OFFSET):
    """
    Mengambil rekapan nutrisi berdasarkan tanggal lokal Indonesia pengguna:
    1. Tanggal terpilih (target_date, default hari ini sesuai tz_offset)
    2. 7 Hari Terakhir (Mingguan)
    3. 30 Hari Terakhir (Bulanan)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    local_now = get_local_now(tz_offset)
    local_today = local_now.date()
    if not target_date:
        target_date = local_today.strftime("%Y-%m-%d")
        
    date_meals = cur.execute("""
        SELECT * FROM meal_logs 
        WHERE user_id = ? AND date(logged_at) = ?
        ORDER BY id DESC
    """, (user_id, target_date)).fetchall()
    
    date_totals = {
        "energy_kcal": round(sum(m["energy_kcal"] for m in date_meals), 1),
        "protein_g": round(sum(m["protein_g"] for m in date_meals), 1),
        "fat_g": round(sum(m["fat_g"] for m in date_meals), 1),
        "carb_g": round(sum(m["carb_g"] for m in date_meals), 1),
        "fiber_g": round(sum(m["fiber_g"] for m in date_meals), 1),
        "sodium_mg": round(sum((m["sodium_mg"] if "sodium_mg" in m.keys() and m["sodium_mg"] else 0.0) for m in date_meals), 1),
        "count": len(date_meals),
        "target_date": target_date
    }
    
    start_7d = (local_today - timedelta(days=6)).strftime("%Y-%m-%d")
    today_limit = local_today.strftime("%Y-%m-%d")
    weekly_rows = cur.execute("""
        SELECT date(logged_at) as day, 
               sum(energy_kcal) as total_kcal,
               count(*) as meals_count
        FROM meal_logs
        WHERE user_id = ? AND date(logged_at) >= ? AND date(logged_at) <= ?
        GROUP BY day
        ORDER BY day ASC
    """, (user_id, start_7d, today_limit)).fetchall()
    
    start_30d = (local_today - timedelta(days=29)).strftime("%Y-%m-%d")
    monthly_row = cur.execute("""
        SELECT sum(energy_kcal) as total_kcal,
               count(DISTINCT date(logged_at)) as active_days,
               count(*) as total_meals
        FROM meal_logs
        WHERE user_id = ? AND date(logged_at) >= ? AND date(logged_at) <= ?
    """, (user_id, start_30d, today_limit)).fetchone()
    
    conn.close()
    
    return {
        "today_meals": [dict(m) for m in date_meals],
        "today_totals": date_totals,
        "weekly_data": [dict(r) for r in weekly_rows],
        "monthly_summary": {
            "total_kcal": round(monthly_row["total_kcal"] or 0.0, 1),
            "active_days": monthly_row["active_days"] or 0,
            "total_meals": monthly_row["total_meals"] or 0
        }
    }

def export_user_data_json(user_id: str) -> str:
    """
    Mengekspor data profil, preferensi, dan seluruh riwayat catatan makan pengguna ke format JSON.
    Berguna sebagai cadangan anti-hilang di sisi perangkat pengguna.
    """
    import json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    user_row = cur.execute("SELECT user_id, display_name, daily_calorie_target, theme_preference, gender, weight_kg, height_cm, age_years, subscription_tier, timezone_offset, focus_goal, created_at FROM users WHERE user_id = ?", (user_id,)).fetchone()
    meal_rows = cur.execute("SELECT dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, portion_multiplier, photo_caption, meal_type, logged_at FROM meal_logs WHERE user_id = ? ORDER BY id ASC", (user_id,)).fetchall()
    custom_rows = cur.execute("SELECT food_name, serving_size, energy_kcal, protein_g, fat_g, carb_g FROM custom_foods WHERE user_id = ?", (user_id,)).fetchall()
    weight_rows = cur.execute("SELECT recorded_date, weight_kg, note FROM weight_logs WHERE user_id = ? ORDER BY recorded_date ASC", (user_id,)).fetchall()
    conn.close()
    
    data = {
        "backup_version": "2.0",
        "exported_at": get_local_now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_profile": dict(user_row) if user_row else {"user_id": user_id},
        "meal_logs": [dict(m) for m in meal_rows],
        "custom_foods": [dict(c) for c in custom_rows],
        "weight_logs": [dict(w) for w in weight_rows]
    }
    return json.dumps(data, indent=2, ensure_ascii=False)

def import_user_data_json(user_id: str, json_str: str) -> tuple[bool, str]:
    """
    Memulihkan kembali riwayat catatan makan & berat badan pengguna dari file JSON cadangan.
    """
    import json
    try:
        data = json.loads(json_str)
        meal_logs = data.get("meal_logs", [])
        weight_logs = data.get("weight_logs", [])
        if not meal_logs and not weight_logs:
            return False, "File cadangan tidak memuat catatan makanan atau berat badan."
            
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        imported_count = 0
        for m in meal_logs:
            cur.execute("""
                SELECT id FROM meal_logs 
                WHERE user_id = ? AND dish_name = ? AND logged_at = ?
            """, (user_id, m["dish_name"], m.get("logged_at", "")))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO meal_logs 
                    (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, portion_multiplier, photo_caption, meal_type, logged_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id,
                    m["dish_name"],
                    m.get("energy_kcal", 0.0),
                    m.get("protein_g", 0.0),
                    m.get("fat_g", 0.0),
                    m.get("carb_g", 0.0),
                    m.get("fiber_g", 0.0),
                    m.get("sodium_mg", 0.0),
                    m.get("portion_multiplier", 1.0),
                    m.get("photo_caption", ""),
                    m.get("meal_type", "Makan Siang"),
                    m.get("logged_at", get_local_now().strftime("%Y-%m-%d %H:%M:%S"))
                ))
                imported_count += 1

        for w in weight_logs:
            if w.get("recorded_date") and w.get("weight_kg"):
                cur.execute("""
                    INSERT OR IGNORE INTO weight_logs (user_id, weight_kg, recorded_date, note)
                    VALUES (?, ?, ?, ?)
                """, (user_id, float(w["weight_kg"]), w["recorded_date"], w.get("note", "")))
                
        conn.commit()
        conn.close()
        return True, f"Berhasil memulihkan {imported_count} catatan makanan!"
    except Exception as e:
        return False, f"Format file cadangan tidak valid: {str(e)}"

def stage_pending_food(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi (100g)", serving_weight: float = 100.0, source_origin: str = "Open Food Facts", submitted_by: str = "system"):
    """
    Menyimpan data pangan baru ke tabel antrean (pending_foods) agar dapat ditinjau/diedit
    terlebih dahulu sebelum dipublikasikan ke database utama (menghindari update mendadak).
    """
    clean_name = food_name.strip()
    if not clean_name or kcal_100 < 0:
        return None
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Cek apakah sudah ada di food_composition atau pending_foods
    if barcode:
        ex_main = cur.execute("SELECT id FROM food_composition WHERE barcode = ?", (barcode.strip(),)).fetchone()
        ex_pend = cur.execute("SELECT id FROM pending_foods WHERE barcode = ? AND status = 'pending'", (barcode.strip(),)).fetchone()
        if ex_main or ex_pend:
            conn.close()
            return None
    ex_name = cur.execute("SELECT id FROM pending_foods WHERE LOWER(food_name) = LOWER(?) AND status = 'pending'", (clean_name,)).fetchone()
    if ex_name:
        conn.close()
        return ex_name[0]
        
    cur.execute("""
        INSERT INTO pending_foods 
        (food_name, category, serving_unit, default_serving_weight, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode, source_origin, submitted_by, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    """, (
        clean_name, category, serving_unit, float(serving_weight),
        round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
        round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
        barcode.strip() if barcode else None, source_origin, submitted_by
    ))
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id

def get_pending_foods(status: str = "pending"):
    """Mengambil daftar pangan yang menunggu kurasi/edit sebelum publikasi."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM pending_foods WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def publish_food_to_catalog(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0, barcode: str = "", serving_unit: str = "1 porsi", serving_weight: float = 100.0, pending_id: int = None):
    """
    Mempublikasikan data pangan yang sudah diverifikasi/diedit ke dalam katalog utama food_composition.
    Jika barcode atau nama sudah ada, melakukan update; jika belum, melakukan insert.
    """
    clean_name = food_name.strip()
    clean_barcode = barcode.strip() if barcode else None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    existing = None
    if clean_barcode:
        existing = cur.execute("SELECT id FROM food_composition WHERE barcode = ? LIMIT 1", (clean_barcode,)).fetchone()
    if not existing:
        existing = cur.execute("SELECT id FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1", (clean_name,)).fetchone()
        
    if existing:
        cur.execute("""
            UPDATE food_composition 
            SET food_name = ?, category = ?, serving_unit = ?, default_serving_weight = ?,
                energy_kcal = ?, protein_g = ?, fat_g = ?, carb_g = ?, fiber_g = ?, sodium_mg = ?,
                barcode = COALESCE(?, barcode)
            WHERE id = ?
        """, (
            clean_name, category, serving_unit, float(serving_weight),
            round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
            round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
            clean_barcode, existing["id"]
        ))
    else:
        code_hash = hashlib.md5(clean_name.encode("utf-8")).hexdigest()[:6].upper()
        food_code = f"MN_{code_hash}"
        cur.execute("""
            INSERT INTO food_composition 
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode)
            VALUES (?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?, ?, ?, ?)
        """, (
            food_code, clean_name, category, serving_unit, float(serving_weight),
            round(float(kcal_100), 1), round(float(p_100), 1), round(float(f_100), 1),
            round(float(c_100), 1), round(float(fib_100), 1), round(float(sod_100), 1),
            clean_barcode
        ))
        
    if pending_id is not None:
        cur.execute("UPDATE pending_foods SET status = 'published' WHERE id = ?", (pending_id,))
        
    conn.commit()
    conn.close()
    return True

def reject_pending_food(pending_id: int):
    """Menolak/menghapus item dari antrean draft."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE pending_foods SET status = 'rejected' WHERE id = ?", (pending_id,))
    conn.commit()
    conn.close()
    return True

if __name__ == "__main__":
    init_user_history_tables()
    print("Tabel users dan meal_logs berhasil dibuat!")

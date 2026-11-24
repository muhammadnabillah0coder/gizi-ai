"""
Aplikasi Nutrisi Cerdas: Pahami Pola Makanmu Berbasis Rujukan Pangan Terverifikasi
Mendukung:
1. Akun Pribadi Terproteksi PIN/Password (Multi-User & Multi-Device)
2. Cek Nutrisi Foto & Teks (1.300+ Data Lab TKPI Kemenkes RI, USDA, & Produk Ritel)
3. Rekapan Harian, Mingguan, & Bulanan (Apple Health Activity Ring & Proyeksi Defisit)
"""

import streamlit as st
from PIL import Image
import os
import json
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse

import importlib
import sqlite3
import food_guardrails
import gemini_extractor
import google_auth
import nutrition_engine
import db_history


def _sync_module_from_disk(mod):
    """Muat ulang modul sibling hanya jika file di disk berubah/lebih baru (aman saat hot-deploy Streamlit Cloud, 0ms reload di rerun biasa)."""
    mod_file = getattr(mod, "__file__", None) or ""
    if mod_file.endswith(".pyc") and os.path.exists(mod_file[:-1]):
        mod_file = mod_file[:-1]
    if not mod_file or not os.path.exists(mod_file):
        return mod
    disk_mtime = round(os.path.getmtime(mod_file), 6)
    if getattr(mod, "_MODULE_MTIME", None) != disk_mtime:
        close_pool = getattr(mod, "close_all_pooled_connections", None)
        if callable(close_pool):
            try:
                close_pool()
            except Exception:
                pass
        mod = importlib.reload(mod)
        setattr(mod, "_MODULE_MTIME", disk_mtime)
    return mod


food_guardrails = _sync_module_from_disk(food_guardrails)
gemini_extractor = _sync_module_from_disk(gemini_extractor)
google_auth = _sync_module_from_disk(google_auth)
nutrition_engine = _sync_module_from_disk(nutrition_engine)
db_history = _sync_module_from_disk(db_history)

from food_guardrails import (
    FoodGuardrailRejected,
    MAX_FREE_UNCLEAR_IMAGE_RETRIES_PER_DAY,
    is_excluded_from_public_catalog,
    open_safe_image,
    sanitize_csv_cell,
    sanitize_html_text,
    validate_extracted_dish_totals,
    validate_food_candidate,
    validate_food_text_query,
)
from gemini_extractor import analyze_food_image, analyze_food_text
from nutrition_engine import (
    calculate_dish_nutrition, fetch_open_food_facts, evaluate_nutri_grade,
    compute_macro_targets, find_best_match
)
from db_history import (
    init_user_history_tables, get_or_create_user, log_meal, delete_meal_log,
    update_meal_log, scale_meal_log_portion, find_duplicate_meals,
    remove_duplicate_meals_for_date, get_frequent_meals, copy_meals_from_date,
    get_user_history_stats, update_calorie_target, update_user_theme,
    add_custom_food, get_custom_foods, delete_custom_food,
    get_user_scan_status, record_scan_usage,
    log_water_intake, get_water_intake,
    is_admin_user, register_user, authenticate_user,
    stage_pending_food, get_pending_foods, publish_food_to_catalog, reject_pending_food,
    export_user_data_json, import_user_data_json,
    get_local_now, create_session_token, verify_session_token, session_token_needs_refresh,
    update_user_preferences, log_weight_entry, get_weight_history, get_logging_streak,
    get_storage_backend_info, get_dashboard_bundle
)
from google_auth import get_google_auth_url, exchange_code_for_user, verify_oauth_state

APP_VERSION = "v4.1.4-beta"
APP_CREATOR = "original by MN"

PATCH_NOTES = [
    {
        "version": "v4.1.4-beta (Terbaru)",
        "date": "25 Nov 2026",
        "highlights": [
            "Desain ulang antarmuka berbasis Unslop dan proporsi warna 60/30/10: kanvas netral hangat, garis hairline tipis, satu aksen hijau botanikal, bebas badge gradien ungu dan emoji dekoratif.",
            "Visualisasi presisi baru: Cincin Kalori SVG terkalibrasi dengan ringkasan makronutrien terpadu, serta grafik asupan 7 hari SVG lengkap dengan garis target harian.",
            "Tipografi tenang Plus Jakarta Sans + IBM Plex Mono (tabular-nums), ritme spasi 4px, radius tersarang konsisten, dan teks antarmuka ringkas tanpa tanda seru."
        ]
    },
    {
        "version": "v4.1.3-beta",
        "date": "22 Nov 2026",
        "highlights": [
            "Normalisasi 45 produk ritel (termasuk Nutella) ke basis per 100g/100ml agar hasil scan barcode cocok dengan label gizi kemasan BPOM.",
            "Audit fisika TKPI & barcode sampel: 18 baris data mentah Panganku/TKPI diperbaiki (bebas anomali Atwater, P+F+C > 100g, dan serat > karbohidrat); tombol sampel Ultra Milk, Indomie, Nutella, & Oreo aktif lokal.",
            "Sinkronisasi berat porsi nyata pada Piring Cepat, Menu Populer, dan pencatat cepat Tab Database."
        ]
    },
    {
        "version": "v4.1.2-beta",
        "date": "19 Nov 2026",
        "highlights": [
            "Upgrade engine Gemini ke `gemini-3.5-flash-lite` untuk mengatasi error 404 model lama (`gemini-2.5-flash-lite`).",
            "Auto-failover model otomatis ke `gemini-3.1-flash-lite` dan `gemini-flash-lite-latest` saat terjadi 404 atau 503 sementara."
        ]
    },
    {
        "version": "v4.1.1-beta",
        "date": "18 Nov 2026",
        "highlights": [
            "Hardening keamanan Bug Hunter Pass 2: kuota Vision AI pada scanner label kemasan, anti-CSRF OAuth `state`, & token sesi bergulir 30 hari.",
            "Proteksi backup & CSV: restore `.json` melewati guardrail pangan/gizi, progress bar aman dari nilai negatif, ekspor CSV bebas formula injection.",
            "Konsistensi batas harian 12.000 kkal & 25 menu/hari pada edit/skala/salin; batas aman gambar 25 megapiksel."
        ]
    },
    {
        "version": "v4.0.0-beta",
        "date": "18 Nov 2026",
        "highlights": [
            "Alur 1-pintu anti-double: semua jalur catat menampilkan Preview sebelum disimpan; ubah sesi/porsi memperbarui catatan yang sama.",
            "Smart porsi loyang/wadah bersama dengan pilihan 0.25x sampai 2x dan checklist bahan.",
            "Edit inline, pembersih menu kembar, chip Sering Dimakan, salin kemarin, target gram makro, & persentase kalori aktual.",
            "Dual-backend cloud database (Supabase PostgreSQL via pg8000 + fallback SQLite) & pencocokan TKPI Gen-2."
        ]
    },
    {
        "version": "v3.0.0-beta",
        "date": "14 Nov 2026",
        "highlights": [
            "Mode Open Beta: akun terdaftar mendapat 5 scan foto/hari dan fitur teks/barcode tanpa batas.",
            "Keamanan sesi HMAC, hashing PBKDF2 bersalt, dan exact-match Admin.",
            "Pelacak berat badan, streak harian, 5 mode fokus klinis, zona waktu WITA default, & cache analisis AI."
        ]
    }
]

_PAGE_ICON_PATH = os.path.join(os.path.dirname(__file__), "logo_nutrisi_cerdas_120.png")
st.set_page_config(
    page_title="Nutrisi Cerdas · Catatan Gizi Berbasis TKPI Kemenkes",
    page_icon=_PAGE_ICON_PATH if os.path.exists(_PAGE_ICON_PATH) else ":material/nutrition:",
    layout="wide",
    initial_sidebar_state="expanded"
)


@st.cache_resource(show_spinner=False)
def _ensure_schema_ready(_mod_mtime: float):
    init_user_history_tables()
    return True


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_dashboard_bundle_cached(uid: str, target_date_str: str, tz_offset: int, mut_ver: int):
    return get_dashboard_bundle(uid, target_date=target_date_str, tz_offset=tz_offset)


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_pending_foods_cached(status_filter: str, mut_ver: int):
    return get_pending_foods(status=status_filter)


@st.cache_data(ttl=180, show_spinner=False)
def _fetch_custom_foods_cached(uid: str, mut_ver: int):
    return get_custom_foods(uid)


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_tkpi_categories_and_count():
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
    cur = conn.cursor()
    rows = cur.execute("SELECT food_name, category FROM food_composition").fetchall()
    conn.close()
    visible_rows = [r for r in rows if not is_excluded_from_public_catalog(r[0] or "")]
    cats = sorted({r[1] for r in visible_rows if r[1]})
    return cats, len(visible_rows)


@st.cache_data(ttl=180, show_spinner=False)
def _search_tkpi_catalog_cached(query_str: str, sel_cat_str: str):
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
    cur = conn.cursor()
    sql = "SELECT food_name, category, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode, serving_unit, default_serving_weight FROM food_composition WHERE 1=1"
    params = []
    if query_str:
        sql += " AND (food_name LIKE ? OR barcode LIKE ?)"
        params.append(f"%{query_str}%")
        params.append(f"%{query_str}%")
    if sel_cat_str != "Semua Kategori":
        sql += " AND category = ?"
        params.append(sel_cat_str)
    sql += " ORDER BY food_name ASC LIMIT 120"
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    filtered = [tuple(r) for r in rows if not is_excluded_from_public_catalog(r[0] or "")]
    return filtered[:50]


def _brand_mark_svg(size: int = 38) -> str:
    """Emblem geometris datar Nutrisi Cerdas (mangkuk & daun tunggal solid, tanpa gradien atau glow)."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 40 40" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Logo Nutrisi Cerdas" '
        f'style="flex-shrink:0; display:block;">'
        f'<rect width="40" height="40" rx="10" fill="var(--accent)"/>'
        f'<path d="M9.5 22.5H30.5C30.1 27.6 25.8 31 20 31C14.2 31 9.9 27.6 9.5 22.5Z" fill="var(--accent-fg)"/>'
        f'<path d="M20 20C20 14.5 23.6 10.5 28.5 10.5C28.5 15.6 25.2 20 20 20Z" fill="var(--accent-fg)"/>'
        f'<path d="M19 20C15 19.6 12.2 16.8 12 13C15.8 13.2 18.6 16 19 20Z" fill="var(--accent-fg)" opacity="0.72"/>'
        f'</svg>'
    )


def _lucide_svg(name: str, size: int = 16) -> str:
    """Ikon garis tunggal Lucide (stroke 1.5, mewarisi warna teks peran aktif)."""
    paths = {
        "utensils": '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
        "check": '<path d="M20 6 9 17l-5-5"/>',
        "alert": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
        "share": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><polyline points="16 6 12 2 8 6"/><line x1="12" x2="12" y1="2" y2="15"/>',
        "droplet": '<path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>',
        "scale": '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/>',
        "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
        "book": '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H19a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H6.5a1 1 0 0 1 0-5H20"/>',
        "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
        "calendar": '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
        "arrow-up-right": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    }
    body = paths.get(name, paths["utensils"])
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" style="flex-shrink:0; display:inline-block; vertical-align:middle;">{body}</svg>'
    )


def _render_calorie_ring_svg(pct_actual: float, today_kcal: float, target_kcal: float) -> str:
    """Moment 1: Cincin presisi SVG terkalibrasi (12 tanda skala lab) tanpa glow/animasi berulang."""
    import math
    r = 50.0
    circ = 2.0 * math.pi * r
    fill_ratio = max(0.0, min(1.0, float(pct_actual) / 100.0))
    dash_offset = circ * (1.0 - fill_ratio)
    arc_color = "var(--danger)" if pct_actual > 105.0 else "var(--accent)"
    ticks_svg = []
    for i in range(12):
        ang = math.radians(i * 30.0 - 90.0)
        x1 = 68.0 + 58.0 * math.cos(ang)
        y1 = 68.0 + 58.0 * math.sin(ang)
        x2 = 68.0 + 62.0 * math.cos(ang)
        y2 = 68.0 + 62.0 * math.sin(ang)
        ticks_svg.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="var(--border-col)" stroke-width="1.2" stroke-linecap="round"/>'
        )
    pct_label = f"{pct_actual:.0f}%" if abs(pct_actual - round(pct_actual)) < 0.05 else f"{pct_actual:.1f}%"
    return (
        f'<svg width="136" height="136" viewBox="0 0 136 136" role="img" '
        f'aria-label="Asupan {today_kcal:,.0f} dari {target_kcal:,.0f} kkal ({pct_label})" '
        f'style="display:block; flex-shrink:0;">'
        f'{"".join(ticks_svg)}'
        f'<circle cx="68" cy="68" r="{r:.0f}" fill="none" stroke="var(--track-bg)" stroke-width="9"/>'
        f'<circle cx="68" cy="68" r="{r:.0f}" fill="none" stroke="{arc_color}" stroke-width="9" '
        f'stroke-linecap="round" stroke-dasharray="{circ:.2f}" stroke-dashoffset="{dash_offset:.2f}" '
        f'transform="rotate(-90 68 68)"/>'
        f'<text x="68" y="65" text-anchor="middle" fill="var(--text-primary)" '
        f'font-family="IBM Plex Mono, monospace" font-size="20" font-weight="500">{pct_label}</text>'
        f'<text x="68" y="83" text-anchor="middle" fill="var(--text-muted)" '
        f'font-family="Plus Jakarta Sans, sans-serif" font-size="11" font-weight="400">dari target</text>'
        f'</svg>'
    )


def _render_weekly_intake_svg(weekly_rows: list, target_kcal: float, active_date_str: str) -> str:
    """Moment 2: Grafik batang 7 hari SVG dengan garis target harian, grid halus, dan satu aksen."""
    day_short_id = {0: "Sen", 1: "Sel", 2: "Rab", 3: "Kam", 4: "Jum", 5: "Sab", 6: "Min"}
    rows = weekly_rows[-7:] if weekly_rows else []
    if not rows:
        return ""

    vals = [float(r.get("total_kcal") or 0.0) for r in rows]
    raw_max = max(max(vals, default=0.0), float(target_kcal or 2000.0), 500.0)
    ceil_val = max(500.0, ((int(raw_max * 1.18) + 499) // 500) * 500)

    w, h = 560, 224
    pad_l, pad_r, pad_t, pad_b = 44, 16, 26, 36
    plot_w = w - pad_l - pad_r
    plot_h = h - pad_t - pad_b

    def y_of(v: float) -> float:
        clamped = max(0.0, min(ceil_val, float(v)))
        return pad_t + plot_h * (1.0 - (clamped / ceil_val))

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Grafik kalori 7 hari dibanding target harian" '
        f'style="width:100%; height:auto; display:block;">'
    ]

    # Gridlines horizontal halus + label mono
    for frac in (0.0, 0.5, 1.0):
        gv = ceil_val * frac
        gy = y_of(gv)
        glbl = f"{gv/1000:.1f}k" if gv >= 1000 else f"{gv:.0f}"
        parts.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" '
            f'stroke="var(--border-col)" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{pad_l - 8}" y="{gy + 4:.1f}" text-anchor="end" fill="var(--text-muted)" '
            f'font-family="IBM Plex Mono, monospace" font-size="10">{glbl}</text>'
        )

    # Garis referensi target harian (putus-putus)
    ty = y_of(target_kcal)
    parts.append(
        f'<line x1="{pad_l}" y1="{ty:.1f}" x2="{w - pad_r}" y2="{ty:.1f}" '
        f'stroke="var(--text-muted)" stroke-width="1.2" stroke-dasharray="4 4"/>'
    )
    parts.append(
        f'<text x="{w - pad_r}" y="{max(pad_t - 6, ty - 6):.1f}" text-anchor="end" fill="var(--text-muted)" '
        f'font-family="IBM Plex Mono, monospace" font-size="10">Target {target_kcal:,.0f}</text>'
    )

    n = len(rows)
    step = plot_w / max(n, 1)
    bar_w = min(40.0, max(18.0, step * 0.48))
    has_active = any(str(r.get("day", ""))[:10] == active_date_str for r in rows)

    for idx, row in enumerate(rows):
        d_str = str(row.get("day", ""))[:10]
        val = float(row.get("total_kcal") or 0.0)
        cx = pad_l + step * idx + step / 2.0
        bx = cx - bar_w / 2.0
        by = y_of(val)
        bh = max(2.0, (pad_t + plot_h) - by) if val > 0 else 2.0

        is_focus = (d_str == active_date_str) or (not has_active and idx == n - 1)
        if is_focus:
            fill_col = "var(--danger)" if val > target_kcal * 1.10 else "var(--accent)"
        else:
            fill_col = "var(--bar-neutral)"

        parts.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bh:.1f}" rx="4" fill="{fill_col}"/>'
        )
        if val > 0:
            val_color = "var(--text-primary)" if is_focus else "var(--text-muted)"
            parts.append(
                f'<text x="{cx:.1f}" y="{max(12.0, by - 6):.1f}" text-anchor="middle" fill="{val_color}" '
                f'font-family="IBM Plex Mono, monospace" font-size="10" font-weight="500">{val:,.0f}</text>'
            )

        try:
            dt_obj = datetime.strptime(d_str, "%Y-%m-%d")
            lbl = f"{day_short_id.get(dt_obj.weekday(), '')} {dt_obj.strftime('%d')}"
        except Exception:
            lbl = d_str[-5:]
        lbl_col = "var(--text-primary)" if is_focus else "var(--text-muted)"
        lbl_w = "500" if is_focus else "400"
        parts.append(
            f'<text x="{cx:.1f}" y="{h - 12}" text-anchor="middle" fill="{lbl_col}" '
            f'font-family="IBM Plex Mono, monospace" font-size="11" font-weight="{lbl_w}">{lbl}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def _render_guardrail_rejection_card(g_err: FoodGuardrailRejected):
    """Menampilkan peringatan penolakan tenang & jelas untuk input non-pangan, ekstrem, atau takaran mustahil."""
    safe_msg = sanitize_html_text(g_err.message)
    if g_err.rejection_type == "unclear_image":
        st.warning(
            f"Foto belum cukup jelas untuk dianalisis. {g_err.message} "
            f"Nyalakan pencahayaan terang dan potret piring tegak lurus dari atas."
        )
        return
    st.markdown(
        f"""
        <div style="background: rgba(185, 28, 28, 0.06); border: 1px solid rgba(185, 28, 28, 0.28); border-radius: 12px; padding: 16px; margin: 12px 0;">
            <div style="display: flex; align-items: center; gap: 8px; font-weight: 500; color: var(--danger); font-size: 0.92rem;">
                <span style="width: 6px; height: 6px; border-radius: 50%; background: var(--danger); flex-shrink: 0;"></span>
                <span>Input ditolak penjaga kualitas pangan</span>
            </div>
            <div style="font-size: 0.88rem; margin-top: 8px; line-height: 1.5; color: var(--text-primary);">{safe_msg}</div>
            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 4px;">Data tidak dihitung sebagai nutrisi dan tidak dimasukkan ke buku harian maupun katalog</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _consume_scan_or_free_unclear(uid: str, tz_offset: int, g_err: FoodGuardrailRejected):
    """Memotong kuota pada foto iseng/non-pangan dan membatasi toleransi gratis foto buram maks. 2x/hari."""
    if g_err.consumes_scan_quota:
        record_scan_usage(uid, tz_offset=tz_offset)
        _mark_db_mutated()
        return
    today_key = get_local_now(tz_offset).strftime("%Y-%m-%d")
    bucket = st.session_state.get("unclear_free_tracker") or {}
    if bucket.get("date") != today_key or bucket.get("uid") != uid:
        bucket = {"date": today_key, "uid": uid, "count": 0}
    bucket["count"] = int(bucket.get("count") or 0) + 1
    st.session_state["unclear_free_tracker"] = bucket
    if bucket["count"] > MAX_FREE_UNCLEAR_IMAGE_RETRIES_PER_DAY:
        record_scan_usage(uid, tz_offset=tz_offset)
        _mark_db_mutated()


def _render_scan_quota_exhausted_notice(active_user: dict, sc_status: dict):
    """Menampilkan informasi batas kuota scan foto harian secara seragam pada semua pemindai visual."""
    max_sc = sc_status["max_scans"]
    if active_user["user_id"] == "Tamu (Demo)":
        st.warning(f"Batas scan foto mode demo tercapai ({max_sc}/{max_sc} hari ini)")
        st.info("Buat akun gratis dalam 15 detik untuk membuka 5 scan foto per hari, atau gunakan tab Ketik & Menu Cepat tanpa batas.")
    else:
        st.warning(f"Kuota scan foto hari ini tercapai ({max_sc}/{max_sc})")
        st.info("Anda tetap dapat mencatat tanpa batas lewat tab Ketik & Menu Cepat, Menu Cepat Beranda, atau Barcode & Manual.")


def _safe_open_uploaded_image(uploaded_file):
    """Membuka foto unggahan dengan proteksi batas piksel 25MP dan penanganan error ramah pengguna."""
    try:
        return open_safe_image(uploaded_file)
    except FoodGuardrailRejected as g_err:
        _render_guardrail_rejection_card(g_err)
    except Exception as exc:
        st.error(f"Gagal membaca file gambar: {exc}")
    return None


def _execute_vision_scan_and_open_preview(
    img_obj,
    prompt_caption: str,
    notice_channel: str,
    active_user: dict,
    tz_offset: int,
    api_key_val: str,
    sc_status: dict,
    spinner_text: str,
    user_caption: str = "",
    source_origin: str = "",
    toast_msg: str = "",
):
    """Menjalankan scan Vision AI secara aman dengan gerbang kuota, guardrail porsi, dan Preview terpadu."""
    if not sc_status.get("can_scan"):
        _render_scan_quota_exhausted_notice(active_user, sc_status)
        return
    if not api_key_val:
        st.warning("API Key AI belum disetel di Secrets server")
        return
    with st.spinner(spinner_text):
        try:
            res = analyze_food_image(img_obj, caption=prompt_caption, api_key=api_key_val)
            calc_chk = calculate_dish_nutrition(res.get("components", []), auto_learn=False)
            validate_extracted_dish_totals(res.get("dish_name", ""), calc_chk["totals"])
            if user_caption:
                res["user_caption"] = user_caption
            if source_origin:
                res["source_origin"] = source_origin
            record_scan_usage(active_user["user_id"], tz_offset=tz_offset)
            _mark_db_mutated()
            _open_food_preview(res, origin_tab="scanner")
            if toast_msg:
                st.toast(toast_msg)
            st.rerun()
        except FoodGuardrailRejected as g_err:
            _consume_scan_or_free_unclear(active_user["user_id"], tz_offset, g_err)
            st.session_state["scanner_guardrail_notice"] = (notice_channel, g_err.rejection_type, g_err.message)
            st.rerun()
        except Exception as exc:
            st.error(f"Gagal memproses gambar: {exc}")


def _analyze_and_open_text_preview(raw_text: str, api_key_val: str, origin_tab: str) -> FoodGuardrailRejected | None:
    """Validasi lokal 0-token lalu analisis teks AI + validasi total porsi sebelum membuka Preview."""
    try:
        clean_q = validate_food_text_query(raw_text)
    except FoodGuardrailRejected as g_err:
        return g_err
    if not api_key_val:
        st.error("API Key belum disetel di Secrets")
        return None
    with st.spinner("Menghitung estimasi nutrisi..."):
        try:
            res = analyze_food_text(clean_q, api_key=api_key_val)
            calc_chk = calculate_dish_nutrition(res.get("components", []), auto_learn=False)
            validate_extracted_dish_totals(res.get("dish_name", ""), calc_chk["totals"])
            res["user_caption"] = clean_q
            _open_food_preview(res, origin_tab=origin_tab)
            st.toast("Preview siap. Atur porsi dan waktu makan sebelum disimpan")
            st.rerun()
        except FoodGuardrailRejected as g_err:
            return g_err
        except Exception as exc:
            st.error(f"Gagal menganalisis menu: {exc}")
    return None


def _mark_db_mutated():
    st.session_state["db_mutation_ver"] = st.session_state.get("db_mutation_ver", 0) + 1


def _reset_ephemeral_user_state():
    """Membersihkan state sementara milik akun sebelumnya saat logout atau berganti akun."""
    st.session_state["nutrition_data"] = None
    st.session_state["last_saved_item"] = None
    st.session_state.pop("prepared_backup_json", None)
    st.session_state.pop("selected_diary_date", None)
    st.session_state.pop("scanner_guardrail_notice", None)


_ensure_schema_ready(getattr(db_history, "_MODULE_MTIME", 0.0))

# Tangani Redirect Google OAuth Callback (?code=...&state=...)
auth_code = st.query_params.get("code", "")
auth_state = st.query_params.get("state", "")
if auth_code:
    if not verify_oauth_state(auth_state):
        st.query_params.clear()
        st.error("Gagal memverifikasi sesi login Google: parameter keamanan `state` tidak valid atau sudah kedaluwarsa. Ulangi proses masuk.")
    else:
        redirect_uri = "https://nutrisi-cerdas.streamlit.app"
        user_info, err_details = exchange_code_for_user(auth_code, redirect_uri)
        if not user_info:
            user_info, err_details = exchange_code_for_user(auth_code, "https://nutrisicerdas.streamlit.app")
            if not user_info:
                user_info, err_details = exchange_code_for_user(auth_code, "http://localhost:8501")

        if user_info and user_info.get("email") and user_info.get("verified_email"):
            email = user_info["email"].strip().lower()
            name = user_info.get("name") or email.split("@")[0]
            u = get_or_create_user(email, display_name=name, auth_provider="google")
            st.session_state["user"] = u
            _reset_ephemeral_user_state()
            _mark_db_mutated()
            st.query_params.clear()
            st.query_params["u"] = u["user_id"]
            st.query_params["s"] = create_session_token(u["user_id"])
            st.query_params["auth"] = "google"
            st.toast(f"Masuk sebagai {name} lewat akun Google")
            st.rerun()
        else:
            st.error(f"Gagal memverifikasi login Google: {err_details}")
            st.caption("Pastikan Redirect URI di Google Cloud Console adalah `https://nutrisi-cerdas.streamlit.app` dan kredensial OAuth sudah disetel di Secrets")

# Inisialisasi Sesi Akun Pengguna dengan Verifikasi Token HMAC TTL 30 Hari (Mencegah Pembajakan ?u=)
saved_user_param = st.query_params.get("u", "")
saved_sig_param = st.query_params.get("s", "")
saved_auth_param = st.query_params.get("auth", "local")

if "user" not in st.session_state:
    safe_auth_param = saved_auth_param if saved_auth_param in {"local", "google"} else "local"
    if saved_user_param and verify_session_token(saved_user_param, saved_sig_param):
        st.session_state["user"] = get_or_create_user(saved_user_param.strip().lower(), auth_provider=safe_auth_param)
    else:
        if saved_user_param and saved_user_param.strip().lower() != "tamu (demo)":
            st.session_state["auth_url_warning"] = saved_user_param.strip()
            st.query_params.clear()
        st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
else:
    active_uid = st.session_state["user"]["user_id"]
    active_auth = st.session_state["user"].get("auth_provider", "local")
    if active_uid != "Tamu (Demo)":
        same_user_param = saved_user_param.strip().lower() == active_uid.lower()
        tok_valid = same_user_param and verify_session_token(active_uid, saved_sig_param)
        if not tok_valid or session_token_needs_refresh(saved_sig_param):
            st.query_params["u"] = active_uid
            st.query_params["s"] = create_session_token(active_uid)
            st.query_params["auth"] = active_auth

if "nutrition_data" not in st.session_state:
    st.session_state["nutrition_data"] = None
if "preview_origin_tab" not in st.session_state:
    st.session_state["preview_origin_tab"] = "scanner"
if "comp_toggle_nonce" not in st.session_state:
    st.session_state["comp_toggle_nonce"] = 0
if "last_saved_item" not in st.session_state:
    st.session_state["last_saved_item"] = None
if "db_mutation_ver" not in st.session_state:
    st.session_state["db_mutation_ver"] = 0

# Deteksi Tema Tersimpan & Data Dashboard Ter-bundle (1 koneksi tunggal + cache antar slider rerun)
current_user = st.session_state["user"]
user_theme = current_user.get("theme_preference") or "Apple Light"
is_google = current_user.get("auth_provider") == "google"
is_admin = is_admin_user(current_user["user_id"])
user_tz = int(current_user.get("timezone_offset") if current_user.get("timezone_offset") is not None else 8)
user_focus = current_user.get("focus_goal") or "Diet Sehat"
local_now = get_local_now(user_tz)
if "selected_diary_date" not in st.session_state:
    st.session_state["selected_diary_date"] = local_now.date()
active_diary_date = st.session_state["selected_diary_date"]
active_diary_date_str = active_diary_date.strftime("%Y-%m-%d")

dash_bundle = _fetch_dashboard_bundle_cached(
    current_user["user_id"],
    active_diary_date_str,
    user_tz,
    st.session_state.get("db_mutation_ver", 0)
)
scan_status = dash_bundle["scan_status"]
stats = dash_bundle["stats"]
streak_days = dash_bundle["streak_days"]
water_data = dash_bundle["water_data"]
w_hist = dash_bundle["weight_history"]
freq_meals = dash_bundle["frequent_meals"]

# Generator CSS Tema 60/30/10 + Standar Unslop (Netral Tenang, Hairline 8-10%, 1 Aksen Kontras >= 4.5:1, Radius Tersarang)
def build_theme_css(
    bg_main: str,
    bg_sidebar: str,
    bg_card: str,
    bg_input: str,
    text_primary: str,
    text_secondary: str,
    text_muted: str,
    border_col: str,
    accent: str,
    accent_fg: str,
    tab_bg: str,
    is_dark: bool = False,
):
    positive = "#4cc38a" if is_dark else "#15803d"
    warning = "#e5a044" if is_dark else "#b45309"
    danger = "#e5484d" if is_dark else "#b91c1c"
    track_bg = "rgba(237, 237, 237, 0.10)" if is_dark else "rgba(28, 25, 23, 0.08)"
    bar_neutral = "rgba(237, 237, 237, 0.22)" if is_dark else "rgba(28, 25, 23, 0.16)"
    card_shadow = "none" if is_dark else "0 1px 2px rgba(28, 25, 23, 0.04)"
    tab_active_shadow = "inset 0 1px 0 rgba(255, 255, 255, 0.08)" if is_dark else "0 1px 2px rgba(28, 25, 23, 0.06)"
    return f"""
        :root {{
            --bg-main: {bg_main};
            --bg-sidebar: {bg_sidebar};
            --bg-card: {bg_card};
            --bg-input: {bg_input};
            --surface-raised: {bg_input};
            --text-primary: {text_primary};
            --text-secondary: {text_secondary};
            --text-muted: {text_muted};
            --border-col: {border_col};
            --accent: {accent};
            --accent-fg: {accent_fg};
            --positive: {positive};
            --warning: {warning};
            --danger: {danger};
            --track-bg: {track_bg};
            --bar-neutral: {bar_neutral};
        }}
        .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{
            background-color: {bg_main} !important;
            color: {text_primary} !important;
        }}
        [data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {{
            background-color: {bg_sidebar} !important;
            color: {text_primary} !important;
            border-right: 1px solid {border_col} !important;
        }}
        .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
        .stApp p, .stApp label, .stApp span, .stApp li, .stApp .stMarkdown,
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4, [data-testid="stSidebar"] h5 {{
            color: {text_primary};
        }}
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p, .theme-muted {{
            color: {text_muted} !important;
        }}
        .nc-card {{
            background: {bg_card} !important;
            color: {text_primary} !important;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid {border_col} !important;
            box-shadow: {card_shadow};
            margin-bottom: 16px;
        }}
        [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"] {{
            background-color: {bg_card} !important;
            border-color: {border_col} !important;
            border-radius: 12px !important;
            color: {text_primary} !important;
            box-shadow: {card_shadow};
        }}
        [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{
            color: {text_primary} !important;
            font-weight: 500 !important;
        }}
        div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"],
        div[data-baseweb="select"] > div {{
            background-color: {bg_input} !important;
            color: {text_primary} !important;
            border-color: {border_col} !important;
            border-radius: 8px !important;
        }}
        div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea,
        div[data-baseweb="select"] span, div[data-baseweb="select"] div {{
            color: {text_primary} !important;
            -webkit-text-fill-color: {text_primary} !important;
        }}
        div[data-baseweb="input"] input::placeholder, div[data-baseweb="textarea"] textarea::placeholder {{
            color: {text_muted} !important;
            -webkit-text-fill-color: {text_muted} !important;
            opacity: 0.9 !important;
        }}
        [data-testid="stFileUploader"], [data-testid="stFileUploaderDropzone"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px dashed {border_col} !important;
            border-radius: 12px !important;
        }}
        [data-testid="stFileUploaderDropzone"] div,
        [data-testid="stFileUploaderDropzone"] span,
        [data-testid="stFileUploaderDropzone"] small {{
            color: {text_secondary} !important;
        }}
        [data-testid="stFileUploaderDropzone"] button {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            border: none !important;
            font-weight: 500 !important;
            border-radius: 8px !important;
        }}
        [data-testid="stFileUploaderDropzone"] button span {{
            color: {accent_fg} !important;
        }}
        [data-testid="stCameraInput"], [data-testid="stCameraInput"] > div {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border-radius: 12px !important;
            border: 1px solid {border_col} !important;
        }}
        [data-testid="stCameraInput"] button {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            font-weight: 500 !important;
            border: none !important;
            border-radius: 8px !important;
        }}
        [data-testid="stCameraInput"] button span, [data-testid="stCameraInput"] span, [data-testid="stCameraInput"] p {{
            color: {text_primary} !important;
        }}
        [data-testid="stCameraInput"] button span {{
            color: {accent_fg} !important;
        }}
        [data-testid="stCameraInput"] a {{
            color: {accent} !important;
            font-weight: 500 !important;
        }}
        [data-testid="stAlert"], div[role="alert"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px solid {border_col} !important;
            border-radius: 12px !important;
        }}
        [data-testid="stAlert"] p, [data-testid="stAlert"] span, [data-testid="stAlert"] div {{
            color: {text_primary} !important;
        }}
        [data-testid="stToast"], [data-testid="stToast"] > div {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px solid {border_col} !important;
            border-radius: 12px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12) !important;
        }}
        [data-testid="stToast"] p, [data-testid="stToast"] span {{
            color: {text_primary} !important;
        }}
        div[data-baseweb="popover"], div[data-baseweb="popover"] > div,
        [data-testid="stPopoverBody"], ul[role="listbox"], li[role="option"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border-color: {border_col} !important;
        }}
        .stButton > button[kind="secondary"], [data-testid="stPopover"] > div > button,
        [data-testid="stDownloadButton"] > button {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px solid {border_col} !important;
        }}
        .stButton > button[kind="secondary"]:hover, [data-testid="stPopover"] > div > button:hover,
        [data-testid="stDownloadButton"] > button:hover {{
            background-color: {bg_input} !important;
            border-color: {text_muted} !important;
        }}
        .stButton > button[kind="secondary"] p, .stButton > button[kind="secondary"] span,
        [data-testid="stPopover"] > div > button p, [data-testid="stPopover"] > div > button span,
        [data-testid="stDownloadButton"] > button p, [data-testid="stDownloadButton"] > button span {{
            color: {text_primary} !important;
        }}
        .stButton > button[kind="primary"], [data-testid="stPopover"] > div > button[kind="primary"] {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            border: 1px solid transparent !important;
        }}
        .stButton > button[kind="primary"]:hover, [data-testid="stPopover"] > div > button[kind="primary"]:hover {{
            opacity: 0.92;
        }}
        .stButton > button[kind="primary"] p, .stButton > button[kind="primary"] span,
        [data-testid="stPopover"] > div > button[kind="primary"] p, [data-testid="stPopover"] > div > button[kind="primary"] span {{
            color: {accent_fg} !important;
        }}
        div[data-baseweb="tab-list"] {{
            gap: 4px;
            background-color: {tab_bg} !important;
            padding: 4px;
            border-radius: 12px;
            margin-bottom: 16px;
            border: 1px solid {border_col};
            flex-wrap: wrap !important;
        }}
        button[data-baseweb="tab"] {{
            border-radius: 8px !important;
            font-size: 0.875rem !important;
            font-weight: 500 !important;
            padding: 8px 14px !important;
            color: {text_secondary} !important;
            background-color: transparent !important;
            flex: 1 1 auto !important;
            justify-content: center !important;
            border: 1px solid transparent !important;
        }}
        button[data-baseweb="tab"] p, button[data-baseweb="tab"] span {{
            color: {text_secondary} !important;
            font-weight: 500 !important;
            font-size: 0.875rem !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px solid {border_col} !important;
            box-shadow: {tab_active_shadow} !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] p,
        button[data-baseweb="tab"][aria-selected="true"] span {{
            color: {text_primary} !important;
            font-weight: 600 !important;
        }}
    """

# 9 Pilihan Tema Netral Terkalibrasi 60/30/10 (Tanpa Glow, Gradien Warna, atau Wash Mencolok)
THEME_STYLES = {
    "System Default": """
        :root {
            --bg-main: transparent;
            --bg-card: rgba(128, 128, 128, 0.05);
            --bg-input: rgba(128, 128, 128, 0.08);
            --surface-raised: rgba(128, 128, 128, 0.08);
            --text-primary: inherit;
            --text-secondary: rgba(128, 128, 128, 0.88);
            --text-muted: #78716c;
            --border-col: rgba(128, 128, 128, 0.16);
            --accent: #15803d;
            --accent-fg: #ffffff;
            --positive: #15803d;
            --warning: #b45309;
            --danger: #b91c1c;
            --track-bg: rgba(128, 128, 128, 0.16);
            --bar-neutral: rgba(128, 128, 128, 0.28);
        }
        .nc-card {
            background: var(--bg-card);
            border: 1px solid var(--border-col);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 16px;
        }
        div[data-baseweb="tab-list"] {
            gap: 4px;
            background-color: rgba(128, 128, 128, 0.10);
            padding: 4px;
            border-radius: 12px;
            margin-bottom: 16px;
            border: 1px solid var(--border-col);
        }
        button[data-baseweb="tab"] {
            border-radius: 8px !important;
            font-size: 0.875rem !important;
            font-weight: 500 !important;
            padding: 8px 14px !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: var(--accent) !important;
            color: #ffffff !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] p,
        button[data-baseweb="tab"][aria-selected="true"] span {
            color: #ffffff !important;
        }
    """,
    "Apple Light": build_theme_css(
        bg_main="#F7F6F2", bg_sidebar="#EFECE6", bg_card="#FFFFFF", bg_input="#F4F2EC",
        text_primary="#1C1917", text_secondary="#57534E", text_muted="#78716C",
        border_col="rgba(28, 25, 23, 0.10)", accent="#15803D", accent_fg="#FFFFFF",
        tab_bg="#EBE7DF", is_dark=False
    ),
    "Cal AI Dark": build_theme_css(
        bg_main="#141415", bg_sidebar="#0F0F11", bg_card="#1B1B1E", bg_input="#242428",
        text_primary="#EDEDED", text_secondary="#A1A1A6", text_muted="#85858B",
        border_col="rgba(237, 237, 237, 0.10)", accent="#34D399", accent_fg="#0B1310",
        tab_bg="#1E1E22", is_dark=True
    ),
    "Mint Fresh": build_theme_css(
        bg_main="#F4F7F5", bg_sidebar="#EAF0EC", bg_card="#FFFFFF", bg_input="#EFF4F1",
        text_primary="#16211B", text_secondary="#46574E", text_muted="#64756C",
        border_col="rgba(22, 33, 27, 0.10)", accent="#15803D", accent_fg="#FFFFFF",
        tab_bg="#E4ECE7", is_dark=False
    ),
    "Warm Sunset": build_theme_css(
        bg_main="#F8F5F0", bg_sidebar="#F0EAE0", bg_card="#FDFBF7", bg_input="#F3EDE4",
        text_primary="#1F1B16", text_secondary="#5E554A", text_muted="#7B7266",
        border_col="rgba(31, 27, 22, 0.10)", accent="#B45309", accent_fg="#FFFFFF",
        tab_bg="#EAE2D6", is_dark=False
    ),
    "Ocean Breeze": build_theme_css(
        bg_main="#F5F7FA", bg_sidebar="#ECEFF4", bg_card="#FFFFFF", bg_input="#F0F3F8",
        text_primary="#111827", text_secondary="#4B5565", text_muted="#6B7487",
        border_col="rgba(17, 24, 39, 0.10)", accent="#0369A1", accent_fg="#FFFFFF",
        tab_bg="#E5EAF1", is_dark=False
    ),
    "Royal Purple Dark": build_theme_css(
        bg_main="#141318", bg_sidebar="#0F0E13", bg_card="#1B1A21", bg_input="#24222B",
        text_primary="#EFEFF4", text_secondary="#A5A3B2", text_muted="#868494",
        border_col="rgba(239, 239, 244, 0.10)", accent="#A78BFA", accent_fg="#120F1C",
        tab_bg="#1F1D26", is_dark=True
    ),
    "Sakura Rose": build_theme_css(
        bg_main="#F9F5F6", bg_sidebar="#F2EAEC", bg_card="#FFFFFF", bg_input="#F5EEF0",
        text_primary="#23171B", text_secondary="#634E55", text_muted="#806C73",
        border_col="rgba(35, 23, 27, 0.10)", accent="#BE123C", accent_fg="#FFFFFF",
        tab_bg="#ECE2E5", is_dark=False
    ),
    "Cyberpunk Gold": build_theme_css(
        bg_main="#151412", bg_sidebar="#100F0D", bg_card="#1D1B18", bg_input="#262420",
        text_primary="#F2EFE9", text_secondary="#AAA398", text_muted="#8A847A",
        border_col="rgba(242, 239, 233, 0.10)", accent="#EAB308", accent_fg="#151412",
        tab_bg="#211F1B", is_dark=True
    ),
}

# Terapkan CSS Global Unslop: Tipografi (Plus Jakarta Sans + IBM Plex Mono), Skala 4px, Tabular Figures, Fokus Keyboard, Motion Tenang
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap');
    html, body, [class*="css"] {{
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    .block-container {{
        max-width: 1360px;
        padding-top: 24px !important;
        padding-bottom: 48px !important;
    }}
    h1, h2, h3, h4, h5, h6 {{
        font-weight: 500 !important;
        letter-spacing: 0 !important;
    }}
    .nc-mono {{
        font-family: 'IBM Plex Mono', ui-monospace, SFMono-Regular, monospace !important;
        font-variant-numeric: tabular-nums !important;
    }}
    .nc-num {{
        font-variant-numeric: tabular-nums !important;
    }}
    .nc-label {{
        font-size: 0.8125rem;
        font-weight: 400;
        color: var(--text-muted);
        line-height: 1.4;
    }}
    .nc-section-title {{
        font-size: 1.05rem;
        font-weight: 600;
        color: var(--text-primary);
        margin: 24px 0 12px 0;
        line-height: 1.3;
    }}
    .nc-meta-dot {{
        width: 6px;
        height: 6px;
        border-radius: 50%;
        display: inline-block;
        flex-shrink: 0;
    }}
    .nc-note-box {{
        background: var(--bg-card);
        border: 1px solid var(--border-col);
        border-radius: 12px;
        padding: 12px 16px;
        font-size: 0.875rem;
        line-height: 1.5;
        margin: 12px 0 16px 0;
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }}
    .nc-macro-grid {{
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 16px;
        padding-top: 16px;
        margin-top: 16px;
        border-top: 1px solid var(--border-col);
    }}
    .nc-macro-cell {{
        min-width: 0;
    }}
    .nc-bar-track {{
        height: 4px;
        border-radius: 4px;
        background: var(--track-bg);
        overflow: hidden;
        margin-top: 8px;
    }}
    .nc-bar-fill {{
        height: 100%;
        border-radius: 4px;
    }}
    .nc-ledger-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--border-col);
        font-size: 0.875rem;
    }}
    .nc-ledger-row:last-child {{
        border-bottom: none;
        padding-bottom: 0;
    }}
    .nc-badge {{
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background: var(--surface-raised);
        border: 1px solid var(--border-col);
        color: var(--text-secondary);
        font-size: 0.75rem;
        font-weight: 500;
        padding: 4px 8px;
        border-radius: 6px;
        line-height: 1.2;
    }}
    .stButton > button, [data-testid="stPopover"] > div > button, [data-testid="stDownloadButton"] > button,
    button[data-baseweb="tab"] {{
        border-radius: 8px !important;
        font-weight: 500 !important;
        padding: 8px 16px !important;
        min-height: 36px;
        cursor: pointer !important;
        transition: color 150ms cubic-bezier(0.22, 1, 0.36, 1),
                    background-color 150ms cubic-bezier(0.22, 1, 0.36, 1),
                    border-color 150ms cubic-bezier(0.22, 1, 0.36, 1),
                    opacity 150ms cubic-bezier(0.22, 1, 0.36, 1),
                    transform 120ms cubic-bezier(0.22, 1, 0.36, 1);
    }}
    .stButton > button:active, [data-testid="stPopover"] > div > button:active {{
        transform: scale(0.985);
    }}
    .stButton > button:focus-visible, [data-testid="stPopover"] > div > button:focus-visible,
    button[data-baseweb="tab"]:focus-visible, a:focus-visible {{
        outline: 2px solid var(--accent) !important;
        outline-offset: 2px !important;
    }}
    .stTabs [data-baseweb="tab-highlight"] {{
        display: none !important;
    }}
    @media (max-width: 768px) {{
        .block-container {{
            padding-top: 16px !important;
            padding-left: 16px !important;
            padding-right: 16px !important;
        }}
        .nc-macro-grid {{
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
        }}
        .stButton > button, [data-testid="stPopover"] > div > button {{
            min-height: 44px;
        }}
    }}
    @media (prefers-reduced-motion: reduce) {{
        *, *::before, *::after {{
            transition: none !important;
            animation: none !important;
        }}
    }}
    {THEME_STYLES.get(user_theme, THEME_STYLES["Apple Light"])}
</style>
""", unsafe_allow_html=True)

# Konstanta pilihan porsi & waktu makan (scan_status sudah dihitung 1x di dash_bundle)

TZ_OPTIONS = {
    7: "WIB (UTC+7, Jawa/Sumatra/Kalbar)",
    8: "WITA (UTC+8, Tanah Grogot/Kaltim/Bali)",
    9: "WIT (UTC+9, Papua/Maluku)"
}
FOCUS_GOALS = [
    "Diet Sehat",
    "Jaga Berat Badan",
    "Ibu Hamil & Menyusui",
    "Kendali Gula (Diabetes)",
    "Kendali Natrium (Hipertensi)"
]

PORTION_OPTIONS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0]
PORTION_LABELS = {
    0.25: "1/4 porsi / potong kecil (0.25x)",
    0.5: "1/2 porsi (0.5x)",
    0.75: "3/4 porsi (0.75x)",
    1.0: "1 porsi standar (1.0x)",
    1.5: "1.5x porsi",
    2.0: "2x porsi",
}
MEAL_SESSION_MAP = {
    "Sarapan": "Sarapan",
    "Makan Siang": "Makan Siang",
    "Makan Malam": "Makan Malam",
    "Camilan": "Camilan",
}


def _infer_meal_type(tz_offset: int) -> str:
    h = get_local_now(tz_offset).hour
    if 4 <= h < 11:
        return "Sarapan"
    if 11 <= h < 16:
        return "Makan Siang"
    if 16 <= h < 21:
        return "Makan Malam"
    return "Camilan"


def _closest_portion_opt(val: float) -> float:
    try:
        v = float(val or 1.0)
    except (TypeError, ValueError):
        v = 1.0
    return min(PORTION_OPTIONS, key=lambda opt: abs(opt - v))


def _normalize_meal_key(raw_mtype: str) -> str:
    if not raw_mtype:
        return "Lainnya"
    for k in ["Sarapan", "Makan Siang", "Makan Malam", "Camilan"]:
        if k.lower() in raw_mtype.lower():
            return k
    return raw_mtype


def _open_food_preview(payload: dict, origin_tab: str = "scanner"):
    """Membuka kartu Preview secara seragam tanpa langsung menyimpan (zero double-save)."""
    clean_payload = dict(payload)
    clean_payload.pop("saved_log_id", None)
    clean_payload.pop("saved_meal_type", None)
    clean_payload.pop("saved_multiplier", None)
    st.session_state["nutrition_data"] = clean_payload
    st.session_state["preview_origin_tab"] = origin_tab
    st.session_state["comp_toggle_nonce"] = st.session_state.get("comp_toggle_nonce", 0) + 1


def format_whatsapp_daily_report(display_name: str, diary_date, today_kcal: float, target_kcal: float, pct_actual: float, today_totals: dict, today_meals: list) -> str:
    """Menyusun laporan WhatsApp rapi per waktu makan dengan persentase aktual."""
    grouped = {}
    for m in today_meals:
        mt = _normalize_meal_key(m.get("meal_type"))
        grouped.setdefault(mt, []).append(m)

    lines = [
        f"*Laporan Nutrisi Harian ({diary_date.strftime('%d %B %Y')})*",
        f"Akun: {display_name}",
        f"*Total Kalori:* {today_kcal:,.1f} / {target_kcal:,.0f} kkal ({pct_actual}%)",
        f"P: {today_totals['protein_g']}g | L: {today_totals['fat_g']}g | K: {today_totals['carb_g']}g | S: {today_totals['fiber_g']}g",
        "",
        "*Daftar Menu:*",
    ]
    idx_num = 1
    for mt in ["Sarapan", "Makan Siang", "Makan Malam", "Camilan", "Lainnya"]:
        if mt not in grouped:
            continue
        lines.append(f"*{mt}*")
        for m in grouped[mt]:
            lines.append(f"{idx_num}. {m['dish_name']} ({m['energy_kcal']} kkal)")
            idx_num += 1

    lines.append("\nNutrisi Cerdas: https://nutrisi-cerdas.streamlit.app")
    return "\n".join(lines)


def render_nutrition_preview_card(context_key: str, active_user: dict, active_date_str: str, tz_offset: int, is_adm: bool):
    """Kartu Preview & Simpan Tunggal Idempoten (anti-double save di semua tab)."""
    data = st.session_state.get("nutrition_data")
    if not data:
        return

    nonce = st.session_state.get("comp_toggle_nonce", 0)
    saved_id = data.get("saved_log_id")
    saved_mt = data.get("saved_meal_type") or ""

    with st.container(border=True):
        if saved_id:
            st.markdown(
                f'<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:10px 12px; border-radius:8px; background:var(--surface-raised); border:1px solid var(--border-col); margin-bottom:12px;">'
                f'<span style="display:inline-flex; align-items:center; gap:8px; font-weight:500; font-size:0.875rem; color:var(--positive);">'
                f'<span class="nc-meta-dot" style="background:var(--positive);"></span>'
                f'Tersimpan di {sanitize_html_text(saved_mt)}</span>'
                f'<span style="font-size:0.8rem; color:var(--text-muted);">Perubahan porsi atau sesi akan memperbarui catatan ini</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:10px 12px; border-radius:8px; background:var(--surface-raised); border:1px solid var(--border-col); margin-bottom:12px;">'
                '<span style="display:inline-flex; align-items:center; gap:8px; font-weight:500; font-size:0.875rem; color:var(--warning);">'
                '<span class="nc-meta-dot" style="background:var(--warning);"></span>'
                'Preview, belum disimpan</span>'
                '<span style="font-size:0.8rem; color:var(--text-muted);">Sesuaikan porsi dan waktu makan lalu simpan</span>'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div style="font-size:1.25rem; font-weight:600; color:var(--text-primary); margin-bottom:4px;">{sanitize_html_text(data.get("dish_name", "Menu Makanan"))}</div>',
            unsafe_allow_html=True,
        )
        serving_ref = (data.get("serving_reference") or "").strip()
        if data.get("is_shared_platter"):
            ref_txt = serving_ref or "1 potong atau 1 porsi makan perorangan"
            st.info(f"Porsi perorangan terdeteksi dari wadah bersama. Patokan 1.0x ditaksir untuk {ref_txt} (sesuaikan 0.25x sampai 2x bila perlu).")
        elif serving_ref:
            st.caption(f"Patokan 1.0x: {serving_ref}")

        all_components = data.get("components", [])
        active_components = all_components
        if len(all_components) > 1:
            with st.expander(f"Komponen piring ({len(all_components)} bahan, lepas centang yang tidak dimakan)", expanded=False):
                chk_cols = st.columns(2)
                chosen = []
                for idx_c, comp in enumerate(all_components):
                    with chk_cols[idx_c % 2]:
                        checked = st.checkbox(
                            f"{comp.get('name', 'Bahan')} (~{comp.get('weight_g', 0)}g)",
                            value=True,
                            key=f"prev_comp_{context_key}_{nonce}_{idx_c}"
                        )
                        if checked:
                            chosen.append(comp)
                active_components = chosen

        if not active_components:
            st.warning("Pilih minimal 1 komponen bahan untuk menghitung kalori")
            if st.button("Tutup preview", key=f"prev_close_empty_{context_key}_{nonce}"):
                st.session_state["nutrition_data"] = None
                st.rerun()
            return

        st.caption("Ukuran porsi")
        default_mult = _closest_portion_opt(data.get("saved_multiplier") or 1.0)
        p_mult = st.select_slider(
            "Porsi:",
            options=PORTION_OPTIONS,
            value=default_mult,
            format_func=lambda x: PORTION_LABELS[x],
            label_visibility="collapsed",
            key=f"prev_mult_{context_key}_{nonce}"
        )

        calc_res = calculate_dish_nutrition(active_components, portion_multiplier=p_mult, auto_learn=False)
        t_tot = calc_res["totals"]

        ng = evaluate_nutri_grade(
            t_tot["energy_kcal"], t_tot["protein_g"], t_tot["fat_g"],
            t_tot["carb_g"], t_tot["fiber_g"], t_tot.get("sodium_mg", 0.0)
        )
        badges_html = "".join([
            f'<span class="nc-badge"><span class="nc-meta-dot" style="background:{b_col};"></span>{sanitize_html_text(b_txt)}</span>'
            for b_txt, b_col in ng["badges"]
        ])
        st.markdown(
            f'<div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; background:var(--surface-raised); border:1px solid var(--border-col); border-radius:8px; padding:12px 16px; margin:12px 0;">'
            f'<div style="display:flex; align-items:center; gap:12px;">'
            f'<div class="nc-mono" style="background:{ng["color"]}; color:#ffffff; font-size:1.15rem; font-weight:500; width:36px; height:36px; border-radius:8px; display:flex; align-items:center; justify-content:center;">{ng["grade"]}</div>'
            f'<div><div style="font-size:0.75rem; color:var(--text-muted);">Indeks Nutri-Grade & GGL</div>'
            f'<div style="font-size:0.9rem; font-weight:500; color:var(--text-primary);">{sanitize_html_text(ng["label"])}</div></div>'
            f'</div>'
            f'<div style="display:flex; gap:8px; flex-wrap:wrap;">{badges_html}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f'<div class="nc-macro-grid" style="margin-top:8px; padding-top:12px;">'
            f'<div class="nc-macro-cell"><div class="nc-label">Kalori</div><div class="nc-mono" style="font-size:1.35rem; font-weight:500; color:var(--text-primary); margin-top:4px;">{t_tot["energy_kcal"]:,.1f} <span style="font-size:0.8rem; color:var(--text-muted);">kkal</span></div></div>'
            f'<div class="nc-macro-cell"><div class="nc-label">Protein</div><div class="nc-mono" style="font-size:1.35rem; font-weight:500; color:var(--text-primary); margin-top:4px;">{t_tot["protein_g"]:.1f} <span style="font-size:0.8rem; color:var(--text-muted);">g</span></div></div>'
            f'<div class="nc-macro-cell"><div class="nc-label">Lemak</div><div class="nc-mono" style="font-size:1.35rem; font-weight:500; color:var(--text-primary); margin-top:4px;">{t_tot["fat_g"]:.1f} <span style="font-size:0.8rem; color:var(--text-muted);">g</span></div></div>'
            f'<div class="nc-macro-cell"><div class="nc-label">Karbohidrat</div><div class="nc-mono" style="font-size:1.35rem; font-weight:500; color:var(--text-primary); margin-top:4px;">{t_tot["carb_g"]:.1f} <span style="font-size:0.8rem; color:var(--text-muted);">g</span></div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        meal_keys = list(MEAL_SESSION_MAP.keys())
        meal_vals = list(MEAL_SESSION_MAP.values())
        target_mt = saved_mt or _infer_meal_type(tz_offset)
        def_idx = meal_vals.index(target_mt) if target_mt in meal_vals else 1

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)
        sel_meal_label = st.radio(
            "Waktu makan",
            meal_keys,
            horizontal=True,
            index=def_idx,
            label_visibility="collapsed",
            key=f"prev_meal_{context_key}_{nonce}"
        )
        sel_meal_clean = MEAL_SESSION_MAP[sel_meal_label]

        if not saved_id:
            col_act1, col_act2 = st.columns([3, 1])
            with col_act1:
                if st.button(f"Simpan ke buku harian ({active_user['display_name']})", type="primary", width="stretch", key=f"prev_btn_save_{context_key}_{nonce}"):
                    try:
                        validate_extracted_dish_totals(data.get("dish_name", ""), t_tot)
                        res_log = log_meal(
                            user_id=active_user["user_id"],
                            dish_name=data.get("dish_name", "Menu Sehat"),
                            totals=t_tot,
                            multiplier=p_mult,
                            caption=data.get("user_caption", ""),
                            meal_type=sel_meal_clean,
                            log_date=active_date_str,
                            tz_offset=tz_offset
                        )
                        st.session_state["last_saved_item"] = res_log
                        st.session_state["nutrition_data"]["saved_log_id"] = res_log["id"]
                        st.session_state["nutrition_data"]["saved_meal_type"] = sel_meal_clean
                        st.session_state["nutrition_data"]["saved_multiplier"] = p_mult
                        _mark_db_mutated()
                        st.toast(f"{data.get('dish_name')} tersimpan ke {sel_meal_clean}")
                        st.rerun()
                    except FoodGuardrailRejected as g_err:
                        _render_guardrail_rejection_card(g_err)
            with col_act2:
                if st.button("Tutup", width="stretch", key=f"prev_btn_clear_{context_key}_{nonce}"):
                    st.session_state["nutrition_data"] = None
                    st.rerun()
        else:
            col_u1, col_u2, col_u3 = st.columns([2.2, 1.3, 1.3])
            with col_u1:
                if st.button(f"Perbarui catatan ({sel_meal_clean})", type="primary", width="stretch", key=f"prev_btn_upd_{context_key}_{nonce}"):
                    try:
                        res_upd = update_meal_log(
                            log_id=saved_id,
                            user_id=active_user["user_id"],
                            dish_name=data.get("dish_name", "Menu Sehat"),
                            totals=t_tot,
                            multiplier=p_mult,
                            meal_type=sel_meal_clean,
                        )
                        if res_upd:
                            st.session_state["last_saved_item"] = res_upd
                        st.session_state["nutrition_data"]["saved_meal_type"] = sel_meal_clean
                        st.session_state["nutrition_data"]["saved_multiplier"] = p_mult
                        _mark_db_mutated()
                        st.toast(f"Catatan diperbarui ke {sel_meal_clean} ({t_tot['energy_kcal']} kkal)")
                        st.rerun()
                    except FoodGuardrailRejected as g_err:
                        _render_guardrail_rejection_card(g_err)
            with col_u2:
                if st.button("Batalkan simpan", width="stretch", key=f"prev_btn_undo_{context_key}_{nonce}"):
                    delete_meal_log(saved_id, active_user["user_id"])
                    st.session_state["nutrition_data"].pop("saved_log_id", None)
                    st.session_state["nutrition_data"].pop("saved_meal_type", None)
                    if st.session_state.get("last_saved_item") and st.session_state["last_saved_item"].get("id") == saved_id:
                        st.session_state["last_saved_item"] = None
                    _mark_db_mutated()
                    st.toast("Simpanan dibatalkan, kembali ke mode preview")
                    st.rerun()
            with col_u3:
                if st.button("Menu baru", width="stretch", key=f"prev_btn_new_{context_key}_{nonce}"):
                    st.session_state["nutrition_data"] = None
                    st.rerun()

        if data.get("health_tip"):
            st.markdown(
                f'<div class="nc-note-box"><span class="nc-meta-dot" style="background:var(--accent); margin-top:7px;"></span>'
                f'<div><strong style="font-weight:500;">Catatan gizi:</strong> {sanitize_html_text(data["health_tip"])}</div></div>',
                unsafe_allow_html=True,
            )

        with st.expander("Rincian komposisi lab & koreksi angka gizi", expanded=False):
            table_rows = [{
                "Bahan": it["input_name"],
                "Referensi Lab": it["tkpi_matched_name"],
                "Berat": f"{it['weight_g']} g",
                "Kalori": f"{it['energy_kcal']} kkal",
                "Protein": f"{it['protein_g']} g",
                "Lemak": f"{it['fat_g']} g",
                "Karbo": f"{it['carb_g']} g"
            } for it in calc_res["items"]]
            st.dataframe(table_rows, width="stretch", hide_index=True)

            st.markdown("##### Koreksi nilai gizi")
            ed_c1, ed_c2 = st.columns(2)
            with ed_c1:
                ed_name = st.text_input("Nama pangan atau produk", value=data.get("dish_name", "Menu Makanan"), max_chars=80, key=f"ed_res_name_{context_key}_{nonce}")
                ed_cat = st.text_input("Kategori pangan", value="Produk Terverifikasi MN", max_chars=60, key=f"ed_res_cat_{context_key}_{nonce}")
                ed_bc = st.text_input("Nomor barcode (opsional)", value=str(data.get("barcode") or ""), max_chars=20, key=f"ed_res_bc_{context_key}_{nonce}")
                ed_serv = st.text_input("Satuan saji", value=str(data.get("serving_unit") or "1 porsi"), max_chars=40, key=f"ed_res_serv_{context_key}_{nonce}")
            with ed_c2:
                ed_kcal = st.number_input("Kalori (kkal)", min_value=0.0, max_value=3500.0, value=min(3500.0, float(t_tot["energy_kcal"])), step=5.0, key=f"ed_res_kcal_{context_key}_{nonce}")
                ed_p = st.number_input("Protein (g)", min_value=0.0, max_value=200.0, value=min(200.0, float(t_tot["protein_g"])), step=0.5, key=f"ed_res_p_{context_key}_{nonce}")
                ed_f = st.number_input("Lemak (g)", min_value=0.0, max_value=200.0, value=min(200.0, float(t_tot["fat_g"])), step=0.5, key=f"ed_res_f_{context_key}_{nonce}")
                ed_c = st.number_input("Karbohidrat (g)", min_value=0.0, max_value=400.0, value=min(400.0, float(t_tot["carb_g"])), step=0.5, key=f"ed_res_c_{context_key}_{nonce}")

            col_pub1, col_pub2 = st.columns(2)
            with col_pub1:
                if st.button("Terapkan koreksi", width="stretch", key=f"btn_apply_edit_local_{context_key}_{nonce}"):
                    try:
                        clean_ed_name = validate_food_candidate(
                            ed_name, ed_kcal, ed_p, ed_f, ed_c,
                            float(t_tot.get("fiber_g", 0.0)), is_catalog_entry=False,
                        )
                    except FoodGuardrailRejected as g_err:
                        _render_guardrail_rejection_card(g_err)
                        return
                    inv_mult = 1.0 / max(p_mult, 0.1)
                    st.session_state["nutrition_data"]["dish_name"] = clean_ed_name
                    st.session_state["nutrition_data"]["components"] = [{
                        "name": clean_ed_name,
                        "weight_g": round(100.0 * inv_mult, 2),
                        "energy_kcal_per_100g": ed_kcal,
                        "protein_g_per_100g": ed_p,
                        "fat_g_per_100g": ed_f,
                        "carb_g_per_100g": ed_c,
                        "fiber_g_per_100g": float(t_tot.get("fiber_g", 0.0)),
                        "sodium_mg_per_100g": float(t_tot.get("sodium_mg", 0.0)),
                        "custom_override": True,
                        "source_label": f"Koreksi Pengguna ({clean_ed_name})"
                    }]
                    if saved_id:
                        new_tot = {
                            "energy_kcal": ed_kcal, "protein_g": ed_p, "fat_g": ed_f,
                            "carb_g": ed_c, "fiber_g": float(t_tot.get("fiber_g", 0.0)),
                            "sodium_mg": float(t_tot.get("sodium_mg", 0.0)),
                        }
                        try:
                            res_upd = update_meal_log(saved_id, active_user["user_id"], dish_name=clean_ed_name, totals=new_tot, multiplier=p_mult, meal_type=sel_meal_clean)
                            if res_upd:
                                st.session_state["last_saved_item"] = res_upd
                            _mark_db_mutated()
                        except FoodGuardrailRejected as g_err:
                            _render_guardrail_rejection_card(g_err)
                            return
                    st.toast("Nilai gizi diperbarui")
                    st.rerun()
            with col_pub2:
                if is_adm:
                    if st.button("Publikasikan ke katalog utama", type="primary", width="stretch", key=f"btn_pub_catalog_now_{context_key}_{nonce}"):
                        try:
                            publish_food_to_catalog(
                                food_name=ed_name, category=ed_cat,
                                kcal_100=ed_kcal, p_100=ed_p, f_100=ed_f, c_100=ed_c,
                                fib_100=float(t_tot.get("fiber_g", 0.0)),
                                barcode=ed_bc, serving_unit=ed_serv, serving_weight=100.0
                            )
                            _fetch_tkpi_categories_and_count.clear()
                            _search_tkpi_catalog_cached.clear()
                            _mark_db_mutated()
                            st.success(f"{ed_name} dipublikasikan ke katalog utama")
                        except FoodGuardrailRejected as g_err:
                            _render_guardrail_rejection_card(g_err)
                else:
                    if st.button("Ajukan ke antrean kurasi admin", type="primary", width="stretch", key=f"btn_stage_catalog_now_{context_key}_{nonce}"):
                        if active_user["user_id"] == "Tamu (Demo)":
                            st.info("Masuk ke akun terdaftar untuk mengajukan usulan ke katalog admin.")
                        else:
                            try:
                                clean_sub = validate_food_candidate(
                                    ed_name, ed_kcal, ed_p, ed_f, ed_c,
                                    float(t_tot.get("fiber_g", 0.0)), is_catalog_entry=True,
                                )
                                pid = stage_pending_food(
                                    food_name=clean_sub, category=ed_cat,
                                    kcal_100=ed_kcal, p_100=ed_p, f_100=ed_f, c_100=ed_c,
                                    fib_100=float(t_tot.get("fiber_g", 0.0)),
                                    barcode=ed_bc, serving_unit=ed_serv, serving_weight=100.0,
                                    source_origin="Koreksi Pengguna", submitted_by=active_user["user_id"]
                                )
                                if pid:
                                    _mark_db_mutated()
                                    st.success("Diajukan ke antrean kurasi admin")
                                else:
                                    st.warning("Item tersebut sudah ada atau menunggu tinjauan admin")
                            except FoodGuardrailRejected as g_err:
                                _render_guardrail_rejection_card(g_err)

# Sidebar: Akun Pribadi & Target Harian (Tenang, Terstruktur, Skala 4px)
with st.sidebar:
    ver_meta_sb = f'<span class="nc-mono" style="font-size:0.72rem; color:var(--text-muted);">{APP_VERSION} · {APP_CREATOR}</span>' if is_admin else '<span style="font-size:0.75rem; color:var(--text-muted);">Open Beta</span>'
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:12px; padding-bottom:16px; margin-bottom:16px; border-bottom:1px solid var(--border-col);">'
        f'{_brand_mark_svg(32)}'
        f'<div style="min-width:0;">'
        f'<div style="font-weight:600; font-size:0.95rem; line-height:1.2; color:var(--text-primary);">Nutrisi Cerdas</div>'
        f'<div style="margin-top:2px;">{ver_meta_sb}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    if current_user["user_id"] == "Tamu (Demo)":
        st.markdown(
            '<div style="background:var(--bg-card); border:1px solid var(--border-col); border-radius:10px; padding:12px; margin-bottom:16px;">'
            '<div style="display:flex; align-items:center; gap:8px; font-size:0.8125rem; font-weight:500; color:var(--warning);">'
            '<span class="nc-meta-dot" style="background:var(--warning);"></span>Mode demo</div>'
            '<div style="font-size:0.8125rem; color:var(--text-secondary); margin-top:6px; line-height:1.45;">'
            'Buat akun gratis dalam 15 detik untuk menyimpan catatan makan, grafik berat badan, dan 5 scan foto per hari.'
            '</div></div>',
            unsafe_allow_html=True,
        )
    else:
        role_meta = "Admin · Tanpa batas" if is_admin else f"Open Beta · {scan_status['scans_today']}/{scan_status['max_scans']} scan foto"
        st.markdown(
            f'<div style="background:var(--bg-card); border:1px solid var(--border-col); border-radius:10px; padding:12px; margin-bottom:12px;">'
            f'<div style="font-weight:500; font-size:0.9rem; color:var(--text-primary);">{sanitize_html_text(current_user["display_name"])}</div>'
            f'<div class="nc-mono" style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">{role_meta}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if st.button("Keluar akun", icon=":material/logout:", width="stretch", key="sb_btn_logout"):
            st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
            _reset_ephemeral_user_state()
            st.query_params.clear()
            _mark_db_mutated()
            st.toast("Anda telah keluar dari akun")
            st.rerun()

    st.markdown('<div style="font-size:0.8125rem; font-weight:500; color:var(--text-secondary); margin:16px 0 8px 0;">Target kalori harian</div>', unsafe_allow_html=True)
    current_target = float(current_user.get("daily_calorie_target") or 2000.0)
    new_target = st.number_input("Target kalori (kkal/hari)", min_value=1000, max_value=4000, value=int(current_target), step=50, key="sb_target_kcal", label_visibility="collapsed")
    if new_target != current_target:
        update_calorie_target(current_user["user_id"], float(new_target))
        st.session_state["user"]["daily_calorie_target"] = float(new_target)
        _mark_db_mutated()
        st.toast("Target kalori diperbarui")
        st.rerun()

    with st.expander("Hitung target ideal (BMR)", expanded=False):
        st.caption("Rumus Mifflin-St Jeor dan acuan AKG Kemenkes RI")
        gender = st.radio("Jenis kelamin", ["Pria", "Wanita"], horizontal=True, key="sb_bmr_gen")
        bb = st.number_input("Berat badan (kg)", min_value=20.0, max_value=250.0, value=min(250.0, max(20.0, float(current_user.get("weight_kg") or 65.0))), step=1.0, key="sb_bmr_bb")
        tb = st.number_input("Tinggi badan (cm)", min_value=80.0, max_value=230.0, value=min(230.0, max(80.0, float(current_user.get("height_cm") or 170.0))), step=1.0, key="sb_bmr_tb")
        usia = st.number_input("Usia (tahun)", min_value=5, max_value=110, value=min(110, max(5, int(current_user.get("age_years") or 25))), step=1, key="sb_bmr_age")
        aktivitas = st.selectbox("Aktivitas harian", [
            "Sedentari (Jarang olahraga / di depan laptop)",
            "Ringan (Olahraga 1-3 hari/minggu)",
            "Sedang (Olahraga 3-5 hari/minggu)",
            "Sangat Aktif (Latihan intensif setiap hari)"
        ], key="sb_bmr_act")
        tujuan = st.selectbox("Tujuan program", [
            "Turunkan Berat Badan (Defisit 400 kkal)",
            "Jaga Berat Badan Ideal (Maintenance)",
            "Tambah Berat / Massa Otot (Surplus 400 kkal)"
        ], key="sb_bmr_goal")

        if st.button("Terapkan target", width="stretch", key="sb_btn_apply_bmr"):
            if gender == "Pria":
                bmr = (10 * bb) + (6.25 * tb) - (5 * usia) + 5
            else:
                bmr = (10 * bb) + (6.25 * tb) - (5 * usia) - 161

            mult_map = {
                "Sedentari (Jarang olahraga / di depan laptop)": 1.2,
                "Ringan (Olahraga 1-3 hari/minggu)": 1.375,
                "Sedang (Olahraga 3-5 hari/minggu)": 1.55,
                "Sangat Aktif (Latihan intensif setiap hari)": 1.725
            }
            tdee = bmr * mult_map[aktivitas]

            if "Turunkan" in tujuan:
                recom_target = round(tdee - 400.0)
            elif "Tambah" in tujuan:
                recom_target = round(tdee + 400.0)
            else:
                recom_target = round(tdee)

            recom_target = max(1200, min(3800, recom_target))
            update_calorie_target(current_user["user_id"], float(recom_target))
            st.session_state["user"]["daily_calorie_target"] = float(recom_target)
            _mark_db_mutated()
            st.success(f"Target kalori diatur menjadi {recom_target} kkal/hari")
            st.rerun()

    with st.expander("Fokus kesehatan & zona waktu", expanded=False):
        focus_idx = FOCUS_GOALS.index(user_focus) if user_focus in FOCUS_GOALS else 0
        sel_focus = st.selectbox("Fokus pemantauan gizi", FOCUS_GOALS, index=focus_idx, key="sb_focus_goal")
        tz_keys = list(TZ_OPTIONS.keys())
        tz_idx = tz_keys.index(user_tz) if user_tz in tz_keys else 1
        sel_tz = st.selectbox("Zona waktu", tz_keys, index=tz_idx, format_func=lambda k: TZ_OPTIONS[k], key="sb_tz_select")
        if sel_focus != user_focus or sel_tz != user_tz:
            update_user_preferences(current_user["user_id"], timezone_offset=sel_tz, focus_goal=sel_focus)
            st.session_state["user"]["timezone_offset"] = sel_tz
            st.session_state["user"]["focus_goal"] = sel_focus
            st.session_state["selected_diary_date"] = get_local_now(sel_tz).date()
            _mark_db_mutated()
            st.toast("Preferensi fokus dan zona waktu disimpan")
            st.rerun()

    with st.expander("Tema tampilan", expanded=False):
        theme_options = list(THEME_STYLES.keys())
        current_idx = theme_options.index(user_theme) if user_theme in theme_options else 1
        selected_theme = st.selectbox("Tema warna", theme_options, index=current_idx, key="sb_theme_picker")
        if selected_theme != user_theme:
            update_user_theme(current_user["user_id"], selected_theme)
            st.session_state["user"]["theme_preference"] = selected_theme
            _mark_db_mutated()
            st.toast(f"Tema diubah ke {selected_theme}")
            st.rerun()

    if current_user["user_id"] != "Tamu (Demo)":
        with st.expander("Cadangan data pribadi", expanded=False):
            st.caption("Unduh atau pulihkan salinan riwayat makan dan berat badan (.json)")
            if st.button("Siapkan file cadangan (.json)", width="stretch", key="sb_btn_prep_json"):
                st.session_state["prepared_backup_json"] = export_user_data_json(current_user["user_id"])
            if st.session_state.get("prepared_backup_json"):
                st.download_button(
                    "Unduh salinan diary (.json)",
                    data=st.session_state["prepared_backup_json"],
                    file_name=f"nutrisi_cerdas_{current_user['user_id']}_{get_local_now(user_tz).strftime('%Y%m%d')}.json",
                    mime="application/json",
                    width="stretch",
                    key="sb_btn_export_json"
                )
            up_bk = st.file_uploader("Pulihkan dari file .json", type=["json"], key="sb_up_restore_json")
            if up_bk and st.button("Pulihkan sekarang", width="stretch", key="sb_btn_do_restore"):
                ok_imp, msg_imp = import_user_data_json(current_user["user_id"], up_bk.getvalue().decode("utf-8-sig", errors="replace"))
                if ok_imp:
                    _mark_db_mutated()
                    st.success(msg_imp)
                    st.rerun()
                else:
                    st.error(msg_imp)

    if is_admin:
        backend_info = get_storage_backend_info()
        with st.expander("Status cloud database (Admin)", expanded=False):
            if backend_info["mode"] == "supabase":
                st.success(f"{backend_info['label']} · Host: `{backend_info['host']}`")
            else:
                st.warning(f"{backend_info['label']}")
                if backend_info.get("error"):
                    st.caption(f"Detail: `{backend_info['error'][:120]}`")
                st.caption(
                    "1. Buat proyek gratis di supabase.com (Region Singapore). "
                    "2. Salin URI PostgreSQL Session Pooler. "
                    "3. Tempel DATABASE_URL di Streamlit Cloud Secrets."
                )

        with st.expander(f"Catatan rilis ({APP_VERSION})", expanded=False):
            st.caption(f"Dikembangkan oleh Muhammad Nabillah ({APP_CREATOR})")
            for p in PATCH_NOTES:
                st.markdown(f"**{p['version']}** · `{p['date']}`")
                for hl in p["highlights"]:
                    st.caption(f"- {hl}")

# Header Brand Utama (Tenang, Tanpa Badge Gradien Ungu / Glow)
if st.session_state.get("auth_url_warning"):
    st.warning(
        f"Untuk menjaga privasi buku harian {st.session_state['auth_url_warning']}, "
        "tautan akun lama memerlukan verifikasi PIN terlebih dahulu. Klik Masuk / Daftar."
    )
    st.session_state.pop("auth_url_warning", None)

col_head1, col_head2 = st.columns([2.2, 1.15], vertical_alignment="center")

with col_head1:
    meta_suffix = f" · {APP_VERSION}" if is_admin else ""
    st.markdown(
        f'<div style="display:flex; align-items:center; gap:14px; padding:4px 0 12px 0;">'
        f'{_brand_mark_svg(40)}'
        f'<div>'
        f'<div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap;">'
        f'<h1 style="font-size:1.5rem; font-weight:600; margin:0; line-height:1.15; color:var(--text-primary);">Nutrisi Cerdas</h1>'
        f'<span class="nc-mono" style="font-size:0.75rem; color:var(--text-muted);">TKPI Kemenkes RI & Open Food Facts{meta_suffix}</span>'
        f'</div>'
        f'<div style="margin-top:4px; font-size:0.875rem; color:var(--text-secondary);">'
        f'Catatan kalori dan makronutrien deterministik berbasis 1.304 data lab pangan'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

with col_head2:
    if is_admin:
        tier_meta = "Admin · Tanpa batas"
    elif current_user["user_id"] == "Tamu (Demo)":
        tier_meta = f"Demo · {scan_status['scans_today']}/{scan_status['max_scans']} scan foto"
    else:
        tier_meta = f"Beta · {scan_status['scans_today']}/{scan_status['max_scans']} scan foto"

    st.markdown(
        f'<div style="display:flex; justify-content:flex-end; align-items:center; gap:8px; margin-bottom:8px; flex-wrap:wrap;">'
        f'<span style="font-size:0.875rem; font-weight:500; color:var(--text-primary);">{sanitize_html_text(current_user["display_name"])}</span>'
        f'<span class="nc-mono" style="font-size:0.75rem; color:var(--text-muted);">{tier_meta}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    c_acc1, c_acc2 = st.columns([1.15, 0.85])
    with c_acc1:
        if current_user["user_id"] == "Tamu (Demo)":
            btn_acc_label = "Masuk / Daftar"
        else:
            btn_acc_label = f"Akun: {current_user['display_name'].split()[0]}"

        with st.popover(btn_acc_label, width="stretch"):
            if current_user["user_id"] != "Tamu (Demo)":
                st.markdown(f"**{current_user['display_name']}**")
                st.caption(f"ID: `{current_user['user_id']}` · Fokus: `{user_focus}`")
                if st.button("Keluar dari akun", type="primary", width="stretch", key="btn_logout_top"):
                    st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
                    _reset_ephemeral_user_state()
                    st.query_params.clear()
                    _mark_db_mutated()
                    st.toast("Anda telah keluar dari akun")
                    st.rerun()
                st.markdown("---")
                st.caption("Ganti akun lain")

            sub_login, sub_reg = st.tabs(["Masuk", "Daftar baru"])

            with sub_login:
                in_uid = st.text_input("Email atau ID pengguna", placeholder="nama@email.com", key="login_uid")
                in_pin = st.text_input("PIN atau password", type="password", placeholder="Minimal 4 karakter", key="login_pin")

                if st.button("Masuk", type="primary", width="stretch", key="btn_do_login"):
                    success, res = authenticate_user(in_uid, in_pin)
                    if success:
                        st.session_state["user"] = res
                        _reset_ephemeral_user_state()
                        st.query_params["u"] = res["user_id"]
                        st.query_params["s"] = create_session_token(res["user_id"])
                        st.query_params["auth"] = "local"
                        _mark_db_mutated()
                        st.toast(f"Masuk sebagai {res['display_name']}")
                        st.rerun()
                    else:
                        st.error(res)

                st.caption("Data diary dilindungi hashing PBKDF2-SHA256 bersalt")

            with sub_reg:
                reg_uid = st.text_input("Email atau ID unik", placeholder="nama@email.com", key="reg_uid")
                reg_name = st.text_input("Nama panggilan", placeholder="Nama tampilan", key="reg_name")
                reg_pin = st.text_input("Buat PIN atau password", type="password", placeholder="Minimal 4 karakter", key="reg_pin")

                c_r1, c_r2 = st.columns(2)
                with c_r1:
                    reg_gender = st.selectbox("Jenis kelamin", ["Pria", "Wanita"], key="reg_gen")
                    reg_bb = st.number_input("Berat (kg)", min_value=20.0, max_value=250.0, value=65.0, step=1.0, key="reg_bb")
                with c_r2:
                    reg_age = st.number_input("Usia (tahun)", min_value=5, max_value=110, value=25, step=1, key="reg_age")
                    reg_tb = st.number_input("Tinggi (cm)", min_value=80.0, max_value=230.0, value=170.0, step=1.0, key="reg_tb")

                reg_focus = st.selectbox("Fokus pemantauan", FOCUS_GOALS, key="reg_focus")
                reg_goal = st.selectbox("Target kalori", [
                    "Turunkan Berat Badan (Defisit 400 kkal)",
                    "Jaga Berat Badan Ideal (Maintenance)",
                    "Tambah Berat / Massa Otot (Surplus 400 kkal)"
                ], key="reg_goal")

                if reg_gender == "Pria":
                    calc_bmr = (10 * reg_bb) + (6.25 * reg_tb) - (5 * reg_age) + 5
                else:
                    calc_bmr = (10 * reg_bb) + (6.25 * reg_tb) - (5 * reg_age) - 161
                calc_tdee = calc_bmr * 1.375
                if "Turunkan" in reg_goal:
                    auto_target = round(calc_tdee - 400.0)
                elif "Tambah" in reg_goal:
                    auto_target = round(calc_tdee + 400.0)
                else:
                    auto_target = round(calc_tdee)
                auto_target = max(1200, min(3800, auto_target))

                st.markdown(
                    f'<div style="background:var(--surface-raised); border:1px solid var(--border-col); padding:10px 12px; border-radius:8px; margin:8px 0; font-size:0.84rem;">'
                    f'Estimasi target harian: <span class="nc-mono" style="font-weight:500;">{auto_target} kkal</span> '
                    f'<span style="color:var(--text-muted);">(BMR {round(calc_bmr)} kkal)</span></div>',
                    unsafe_allow_html=True,
                )

                reg_target = st.number_input("Target kalori (kkal/hari)", min_value=1000, max_value=4000, value=int(auto_target), step=50, key="reg_kcal")

                if st.button("Daftar akun gratis", type="primary", width="stretch", key="btn_do_reg"):
                    if not reg_pin.strip() or len(reg_pin.strip()) < 4:
                        st.error("PIN atau password minimal 4 karakter")
                    else:
                        success, res = register_user(
                            reg_uid, reg_name, reg_pin,
                            gender=reg_gender, bb=reg_bb, tb=reg_tb, age=int(reg_age),
                            target_kcal=float(reg_target), focus_goal=reg_focus, timezone_offset=8
                        )
                        if success:
                            st.session_state["user"] = res
                            _reset_ephemeral_user_state()
                            st.query_params["u"] = res["user_id"]
                            st.query_params["s"] = create_session_token(res["user_id"])
                            st.query_params["auth"] = "local"
                            _mark_db_mutated()
                            st.toast("Akun dibuat. Kuota 5 scan foto per hari aktif")
                            st.rerun()
                        else:
                            st.error(res)

    with c_acc2:
        with st.popover("Info Beta", width="stretch"):
            st.markdown("##### Program Open Beta")
            st.caption("Seluruh fitur dibuka gratis untuk pengguna uji coba tanpa pembayaran")

            if is_admin:
                st.success("Status: Admin (tanpa batas)")
            elif current_user["user_id"] == "Tamu (Demo)":
                st.info(f"Mode demo: {scan_status['scans_today']}/{scan_status['max_scans']} scan foto hari ini")
                st.markdown(
                    "Akun terdaftar (gratis) mencakup:\n"
                    "- 5 scan foto makanan per hari\n"
                    "- Pelacak berat badan dan streak harian\n"
                    "- 5 mode fokus klinis (Diet, Ibu Hamil, Diabetes, Hipertensi)\n"
                    "- Catat teks, barcode, dan menu cepat tanpa batas"
                )
            else:
                sisa_scan = max(0, scan_status["max_scans"] - scan_status["scans_today"])
                st.success(f"Sisa scan foto hari ini: {sisa_scan}/{scan_status['max_scans']}")
                st.markdown(
                    "Fasilitas akun aktif:\n"
                    "- 5 scan foto makanan per hari\n"
                    "- Catat teks, menu cepat, dan barcode tanpa batas\n"
                    "- Grafik berat badan, streak harian, dan fokus klinis"
                )

# Banner Ringkas untuk Pengunjung Tamu (Tanpa Pill / Tanpa Hype)
if current_user["user_id"] == "Tamu (Demo)":
    with st.container(border=True):
        c_hero_txt, c_hero_act = st.columns([2.5, 1.0], vertical_alignment="center")
        with c_hero_txt:
            st.markdown(
                '<div style="font-size:1.0rem; font-weight:600; color:var(--text-primary); margin-bottom:4px;">'
                'Simpan catatan makan di akun pribadi</div>'
                '<div style="font-size:0.875rem; color:var(--text-secondary); line-height:1.5;">'
                'Anda berada di mode demo. Buat akun gratis dengan nama dan 4 digit PIN untuk menyimpan riwayat, '
                'grafik berat badan, dan kuota 5 scan foto per hari.'
                '</div>',
                unsafe_allow_html=True,
            )

        with c_hero_act:
            with st.popover("Buat akun gratis", type="primary", width="stretch"):
                st.markdown("##### Pendaftaran akun baru")
                st.caption("Hitung target kalori otomatis dan simpan riwayat Anda")
                h_uid = st.text_input("Email atau ID unik", placeholder="nama@email.com", key="h_reg_uid")
                h_name = st.text_input("Nama panggilan", placeholder="Nama tampilan", key="h_reg_name")
                h_pin = st.text_input("Buat PIN atau password", type="password", placeholder="Minimal 4 karakter", key="h_reg_pin")

                hc_1, hc_2 = st.columns(2)
                with hc_1:
                    h_gender = st.selectbox("Jenis kelamin", ["Pria", "Wanita"], key="h_reg_gen")
                    h_bb = st.number_input("Berat (kg)", min_value=20.0, max_value=250.0, value=65.0, step=1.0, key="h_reg_bb")
                with hc_2:
                    h_age = st.number_input("Usia (tahun)", min_value=5, max_value=110, value=25, step=1, key="h_reg_age")
                    h_tb = st.number_input("Tinggi (cm)", min_value=80.0, max_value=230.0, value=170.0, step=1.0, key="h_reg_tb")

                h_focus = st.selectbox("Fokus kesehatan", FOCUS_GOALS, key="h_reg_focus")
                h_goal = st.selectbox("Tujuan program", [
                    "Turunkan Berat Badan (Defisit 400 kkal)",
                    "Jaga Berat Badan Ideal (Maintenance)",
                    "Tambah Berat / Massa Otot (Surplus 400 kkal)"
                ], key="h_reg_goal")

                if h_gender == "Pria":
                    h_bmr = (10 * h_bb) + (6.25 * h_tb) - (5 * h_age) + 5
                else:
                    h_bmr = (10 * h_bb) + (6.25 * h_tb) - (5 * h_age) - 161

                h_tdee = h_bmr * 1.375
                if "Turunkan" in h_goal:
                    h_target = round(h_tdee - 400.0)
                elif "Tambah" in h_goal:
                    h_target = round(h_tdee + 400.0)
                else:
                    h_target = round(h_tdee)
                h_target = max(1200, min(3800, h_target))

                st.markdown(
                    f'<div style="background:var(--surface-raised); border:1px solid var(--border-col); padding:10px 12px; border-radius:8px; margin:8px 0; font-size:0.84rem;">'
                    f'Estimasi target harian: <span class="nc-mono" style="font-weight:500;">{h_target} kkal</span> '
                    f'<span style="color:var(--text-muted);">(BMR {round(h_bmr)} kkal)</span></div>',
                    unsafe_allow_html=True,
                )

                h_custom_target = st.number_input("Target kalori awal (kkal/hari)", min_value=1000, max_value=4000, value=int(h_target), step=50, key="h_reg_target")

                if st.button("Daftar & mulai catat", type="primary", width="stretch", key="h_btn_submit"):
                    if not h_uid.strip() or len(h_pin.strip()) < 4:
                        st.error("ID atau email wajib diisi dan PIN minimal 4 karakter")
                    else:
                        success, res = register_user(
                            h_uid, h_name, h_pin,
                            gender=h_gender, bb=h_bb, tb=h_tb,
                            age=int(h_age), target_kcal=float(h_custom_target),
                            focus_goal=h_focus, timezone_offset=8
                        )
                        if success:
                            st.session_state["user"] = res
                            _reset_ephemeral_user_state()
                            st.query_params["u"] = res["user_id"]
                            st.query_params["s"] = create_session_token(res["user_id"])
                            st.query_params["auth"] = "local"
                            _mark_db_mutated()
                            st.toast("Akun dibuat. Kuota 5 scan foto per hari aktif")
                            st.rerun()
                        else:
                            st.error(res)

# Deteksi Gemini API Key (Global)
api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    try:
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

# Navigasi Utama (Bersih Tanpa Emoji, Ringkas 1 Baris di HP)
tab_diary, tab_scanner, tab_sources, tab_guide = st.tabs([
    "Hari Ini",
    "Catat",
    "Database",
    "Bantuan"
])

# Inisialisasi Tanggal Aktif Dashboard berdasarkan Zona Waktu Lokal Pengguna (WITA default)
local_now = get_local_now(user_tz)
if "selected_diary_date" not in st.session_state:
    st.session_state["selected_diary_date"] = local_now.date()

active_diary_date = st.session_state["selected_diary_date"]
active_diary_date_str = active_diary_date.strftime("%Y-%m-%d")

stats = dash_bundle["stats"]
streak_days = dash_bundle["streak_days"]
target_kcal = float(st.session_state["user"].get("daily_calorie_target") or 2000.0)
today_kcal = stats["today_totals"]["energy_kcal"]
pct_today_actual = round((today_kcal / target_kcal) * 100, 1) if target_kcal > 0 else 0.0
pct_today_bar = max(0.0, min(pct_today_actual / 100.0, 1.0))
macro_targets = compute_macro_targets(target_kcal, user_focus)

# ================= TAB 1: DASHBOARD REKAPAN KALORI =================
with tab_diary:
    c_date1, c_date2, c_date3, c_date4 = st.columns([1.0, 1.0, 1.5, 2.5], vertical_alignment="center")
    today_dt = local_now.date()
    yesterday_dt = today_dt - timedelta(days=1)

    with c_date1:
        if st.button("Hari ini", width="stretch", type="primary" if active_diary_date == today_dt else "secondary"):
            st.session_state["selected_diary_date"] = today_dt
            st.rerun()
    with c_date2:
        if st.button("Kemarin", width="stretch", type="primary" if active_diary_date == yesterday_dt else "secondary"):
            st.session_state["selected_diary_date"] = yesterday_dt
            st.rerun()
    with c_date3:
        pick_d = st.date_input("Pilih tanggal", value=active_diary_date, max_value=today_dt + timedelta(days=7), key="dash_datepicker", label_visibility="collapsed")
        if pick_d != active_diary_date:
            st.session_state["selected_diary_date"] = pick_d
            st.rerun()
    with c_date4:
        day_id = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}.get(active_diary_date.strftime('%A'), active_diary_date.strftime('%A'))
        tz_short = {7: "WIB", 8: "WITA", 9: "WIT"}.get(user_tz, "WITA")
        st.markdown(
            f'<div class="nc-mono" style="text-align:right; font-size:0.84rem; color:var(--text-secondary);">'
            f'{day_id}, {active_diary_date.strftime("%d %b %Y")} · {tz_short}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

    # Notifikasi Tenang Penyimpanan Terakhir
    if "last_saved_item" in st.session_state and st.session_state["last_saved_item"]:
        saved_info = st.session_state["last_saved_item"]
        st.markdown(
            f'<div style="background:var(--bg-card); border:1px solid var(--border-col); border-radius:10px; padding:12px 16px; margin-bottom:16px; display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">'
            f'<div style="display:flex; align-items:center; gap:10px; font-size:0.875rem;">'
            f'<span class="nc-meta-dot" style="background:var(--positive);"></span>'
            f'<span><strong style="font-weight:500;">Tersimpan:</strong> {sanitize_html_text(saved_info["dish_name"])} '
            f'<span class="nc-mono" style="color:var(--text-secondary);">({saved_info["energy_kcal"]} kkal)</span></span>'
            f'</div>'
            f'<span class="nc-mono" style="font-size:0.78rem; color:var(--text-muted);">{sanitize_html_text(saved_info["meal_type"])} · {sanitize_html_text(saved_info["saved_at"])}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # MOMENT 1: Kartu Presisi Kalori & Makronutrien Terpadu (SVG Cincin Terkalibrasi + 4 Bar Makro)
    p_g = stats['today_totals']['protein_g']
    f_g = stats['today_totals']['fat_g']
    c_g = stats['today_totals']['carb_g']
    fib_g = stats['today_totals']['fiber_g']
    sod_mg = stats['today_totals'].get('sodium_mg', 0.0)

    kcal_delta = target_kcal - today_kcal
    if kcal_delta >= 0:
        budget_html = f'<span style="color:var(--text-secondary);">Sisa budget <span class="nc-mono" style="color:var(--text-primary); font-weight:500;">{kcal_delta:,.0f} kkal</span></span>'
    else:
        budget_html = f'<span style="color:var(--danger);">Melebihi target <span class="nc-mono" style="font-weight:500;">+{abs(kcal_delta):,.0f} kkal</span></span>'

    streak_text = f"Streak {streak_days} hari" if streak_days > 0 else "Belum ada streak"
    p_fill = min(100.0, (p_g / max(1.0, macro_targets['protein_g'])) * 100.0)
    f_fill = min(100.0, (f_g / max(1.0, macro_targets['fat_g'])) * 100.0)
    c_fill = min(100.0, (c_g / max(1.0, macro_targets['carb_g'])) * 100.0)
    fib_fill = min(100.0, (fib_g / max(1.0, macro_targets['fiber_g'])) * 100.0)
    ring_svg = _render_calorie_ring_svg(pct_today_actual, today_kcal, target_kcal)

    st.markdown(
        f'<div class="nc-card">'
        f'  <div style="display:flex; justify-content:space-between; align-items:center; gap:20px; flex-wrap:wrap;">'
        f'    <div style="flex:1 1 260px; min-width:0;">'
        f'      <div class="nc-label">Asupan kalori · {sanitize_html_text(user_focus)}</div>'
        f'      <div class="nc-mono" style="font-size:2.15rem; font-weight:500; line-height:1.15; margin:8px 0 6px 0; color:var(--text-primary);">'
        f'        {today_kcal:,.1f} <span style="font-size:1.0rem; font-weight:400; color:var(--text-muted);">/ {target_kcal:,.0f} kkal</span>'
        f'      </div>'
        f'      <div style="font-size:0.875rem; margin-bottom:12px;">{budget_html}</div>'
        f'      <div class="nc-mono" style="display:flex; gap:16px; flex-wrap:wrap; font-size:0.78rem; color:var(--text-muted);">'
        f'        <span>{stats["today_totals"]["count"]} menu tercatat</span>'
        f'        <span>{streak_text}</span>'
        f'        <span>Natrium {sod_mg:,.0f} / {macro_targets["sodium_mg"]:,.0f} mg</span>'
        f'      </div>'
        f'    </div>'
        f'    {ring_svg}'
        f'  </div>'
        f'  <div class="nc-macro-grid">'
        f'    <div class="nc-macro-cell">'
        f'      <div class="nc-label">Protein</div>'
        f'      <div class="nc-mono" style="font-size:1.1rem; font-weight:500; margin-top:4px; color:var(--text-primary);">{p_g:.1f}g <span style="font-size:0.75rem; color:var(--text-muted);">/ {macro_targets["protein_g"]:.0f}g</span></div>'
        f'      <div class="nc-bar-track"><div class="nc-bar-fill" style="width:{p_fill:.1f}%; background:#0369a1;"></div></div>'
        f'    </div>'
        f'    <div class="nc-macro-cell">'
        f'      <div class="nc-label">Lemak</div>'
        f'      <div class="nc-mono" style="font-size:1.1rem; font-weight:500; margin-top:4px; color:var(--text-primary);">{f_g:.1f}g <span style="font-size:0.75rem; color:var(--text-muted);">/ {macro_targets["fat_g"]:.0f}g</span></div>'
        f'      <div class="nc-bar-track"><div class="nc-bar-fill" style="width:{f_fill:.1f}%; background:#b45309;"></div></div>'
        f'    </div>'
        f'    <div class="nc-macro-cell">'
        f'      <div class="nc-label">Karbohidrat</div>'
        f'      <div class="nc-mono" style="font-size:1.1rem; font-weight:500; margin-top:4px; color:var(--text-primary);">{c_g:.1f}g <span style="font-size:0.75rem; color:var(--text-muted);">/ {macro_targets["carb_g"]:.0f}g</span></div>'
        f'      <div class="nc-bar-track"><div class="nc-bar-fill" style="width:{c_fill:.1f}%; background:var(--accent);"></div></div>'
        f'    </div>'
        f'    <div class="nc-macro-cell">'
        f'      <div class="nc-label">Serat</div>'
        f'      <div class="nc-mono" style="font-size:1.1rem; font-weight:500; margin-top:4px; color:var(--text-primary);">{fib_g:.1f}g <span style="font-size:0.75rem; color:var(--text-muted);">/ {macro_targets["fiber_g"]:.0f}g</span></div>'
        f'      <div class="nc-bar-track"><div class="nc-bar-fill" style="width:{fib_fill:.1f}%; background:#6d28d9;"></div></div>'
        f'    </div>'
        f'  </div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Smart Daily Balancer (Beradaptasi dengan Fokus Kesehatan, Tanpa Garis Kiri Tebal / Tanda Seru)
    rem_kcal = max(0.0, target_kcal - today_kcal)
    prot_ratio = 0.25 if "Hamil" in user_focus else 0.22
    target_prot = round((target_kcal * prot_ratio) / 4.0)
    if stats['today_totals']['count'] > 0:
        if "Hipertensi" in user_focus and sod_mg >= 1800.0:
            balancer_msg = f"Asupan natrium hari ini mencapai {sod_mg:,.0f} mg (mendekati batas 2.000 mg Kemenkes/WHO). Kurangi makanan asin, kecap, dan kuah kaldu pada sesi berikutnya."
            balancer_dot = "var(--danger)"
        elif "Diabetes" in user_focus and c_g > (target_kcal * 0.55 / 4.0) and fib_g < 15.0:
            balancer_msg = f"Karbohidrat tercatat {c_g}g dengan serat {fib_g}g. Tambahkan sayuran berserat dan protein di porsi berikutnya agar kurva gula darah lebih landai."
            balancer_dot = "var(--warning)"
        elif "Hamil" in user_focus and p_g < target_prot * 0.6:
            balancer_msg = f"Asupan protein tercatat {p_g}g dari target {target_prot}g. Tambahkan sumber protein hewani seperti ikan kembung, telur, ayam, atau susu."
            balancer_dot = "#0369a1"
        elif p_g < target_prot * 0.5 and rem_kcal > 250:
            balancer_msg = f"Asupan protein masih {p_g}g dari target {target_prot}g. Tambahkan 2 butir telur rebus (+12g), dada ayam bakar (+28g), atau tempe/tahu."
            balancer_dot = "#0369a1"
        elif fib_g < 10.0 and rem_kcal > 150:
            balancer_msg = f"Serat pangan tercatat {fib_g}g dari target 25g. Tambahkan sayur bening, capcay, atau 1 potong buah pepaya."
            balancer_dot = "var(--positive)"
        elif rem_kcal <= 150 and today_kcal <= target_kcal * 1.05:
            balancer_msg = f"Sisa budget kalori hari ini {rem_kcal:.0f} kkal. Cukup air putih atau teh tawar hangat untuk menutup hari."
            balancer_dot = "var(--positive)"
        elif today_kcal > target_kcal * 1.05:
            balancer_msg = f"Asupan melewati target sebesar +{today_kcal - target_kcal:.0f} kkal. Seimbangkan dengan jalan kaki santai 20 sampai 30 menit dan kurangi porsi karbohidrat besok."
            balancer_dot = "var(--warning)"
        else:
            balancer_msg = f"Komposisi makan terjaga baik dengan sisa budget {rem_kcal:.0f} kkal. Pertahankan porsi protein dan hidrasi."
            balancer_dot = "var(--positive)"

        st.markdown(
            f'<div class="nc-note-box">'
            f'<span class="nc-meta-dot" style="background:{balancer_dot}; margin-top:7px;"></span>'
            f'<div><strong style="font-weight:500;">Penyeimbang harian ({sanitize_html_text(user_focus)}):</strong> {balancer_msg}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Catat Cepat Menu Makan Hari Ini (Seragam: Selalu Preview Dulu)
    with st.container(border=True):
        st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px; color:var(--text-primary);">Catat cepat menu makan</div>', unsafe_allow_html=True)
        qc_col1, qc_col2 = st.columns([3.3, 1.2], vertical_alignment="center")
        with qc_col1:
            dash_quick_text = st.text_input(
                "Menu makanan",
                placeholder="1 potong bingka pisang, atau 1 porsi soto ayam dan nasi",
                key="dash_quick_input",
                label_visibility="collapsed"
            )
        with qc_col2:
            dash_btn_calc = st.button("Hitung & preview", type="primary", width="stretch", key="btn_dash_quick")

        freq_meals = dash_bundle.get("frequent_meals") or []
        if freq_meals:
            st.caption("Sering dimakan")
            fq_cols = st.columns(3)
            for idx_fq, fq_item in enumerate(freq_meals):
                with fq_cols[idx_fq % 3]:
                    if st.button(f"{fq_item['dish_name'][:22]} ({fq_item['energy_kcal']:.0f} kkal)", width="stretch", key=f"dash_fq_{idx_fq}"):
                        _open_food_preview({
                            "dish_name": fq_item["dish_name"],
                            "confidence": "high",
                            "portion_category": "1 porsi kebiasaan Anda",
                            "serving_reference": "1 porsi sesuai catatan sebelumnya",
                            "user_caption": f"Sering dimakan ({fq_item['freq']}x)",
                            "components": [{
                                "name": fq_item["dish_name"],
                                "weight_g": 100.0,
                                "energy_kcal_per_100g": fq_item["energy_kcal"],
                                "protein_g_per_100g": fq_item["protein_g"],
                                "fat_g_per_100g": fq_item["fat_g"],
                                "carb_g_per_100g": fq_item["carb_g"],
                                "fiber_g_per_100g": fq_item["fiber_g"],
                                "sodium_mg_per_100g": fq_item["sodium_mg"],
                                "custom_override": True,
                                "source_label": "Riwayat Pribadi (1.0x)"
                            }],
                            "health_tip": "Sesuaikan porsi dan sesi makan di bawah sebelum disimpan."
                        }, origin_tab="diary")
                        st.rerun()

        st.caption("Menu cepat Indonesia")
        QUICK_PLATES = [
            ("Nasi + Telur Dadar", "Nasi Putih + Telur Dadar", 220.0, {"energy_kcal": 315.0, "protein_g": 11.5, "fat_g": 12.0, "carb_g": 40.0, "fiber_g": 1.0, "sodium_mg": 240.0}),
            ("Nasi + Ayam Bakar", "Nasi Putih + Ayam Bakar Dada", 240.0, {"energy_kcal": 385.0, "protein_g": 32.0, "fat_g": 8.5, "carb_g": 43.0, "fiber_g": 1.2, "sodium_mg": 380.0}),
            ("Bakso Sapi Kuah", "Semangkuk Bakso Sapi Kuah", 350.0, {"energy_kcal": 340.0, "protein_g": 18.5, "fat_g": 11.0, "carb_g": 41.0, "fiber_g": 2.0, "sodium_mg": 680.0}),
            ("Gado-Gado Telur", "Gado-Gado Lontong + Telur Rebus", 300.0, {"energy_kcal": 410.0, "protein_g": 16.0, "fat_g": 18.0, "carb_g": 46.0, "fiber_g": 5.5, "sodium_mg": 420.0}),
            ("Kopi Susu Aren", "Es Kopi Susu Gula Aren", 250.0, {"energy_kcal": 175.0, "protein_g": 4.2, "fat_g": 5.5, "carb_g": 27.0, "fiber_g": 0.0, "sodium_mg": 65.0}),
            ("2 Telur Rebus", "2 Butir Telur Ayam Rebus", 110.0, {"energy_kcal": 154.0, "protein_g": 12.6, "fat_g": 10.6, "carb_g": 1.1, "fiber_g": 0.0, "sodium_mg": 140.0}),
        ]
        qp_cols = st.columns(3)
        for idx_qp, (qp_label, qp_name, qp_w, qp_tot) in enumerate(QUICK_PLATES):
            with qp_cols[idx_qp % 3]:
                if st.button(qp_label, width="stretch", key=f"dash_qp_{idx_qp}"):
                    scale_qp = 100.0 / float(qp_w)
                    _open_food_preview({
                        "dish_name": qp_name,
                        "confidence": "high",
                        "portion_category": "1 porsi standar",
                        "serving_reference": f"1 porsi standar (~{qp_w:.0f}g)",
                        "user_caption": "Menu cepat 1-klik",
                        "components": [{
                            "name": qp_name,
                            "weight_g": float(qp_w),
                            "energy_kcal_per_100g": round(qp_tot["energy_kcal"] * scale_qp, 4),
                            "protein_g_per_100g": round(qp_tot["protein_g"] * scale_qp, 4),
                            "fat_g_per_100g": round(qp_tot["fat_g"] * scale_qp, 4),
                            "carb_g_per_100g": round(qp_tot["carb_g"] * scale_qp, 4),
                            "fiber_g_per_100g": round(qp_tot["fiber_g"] * scale_qp, 4),
                            "sodium_mg_per_100g": round(qp_tot["sodium_mg"] * scale_qp, 4),
                            "custom_override": True,
                            "source_label": "Standar Menu Populer"
                        }],
                        "health_tip": "Pilih ukuran porsi dan sesi makan lalu simpan ke buku harian."
                    }, origin_tab="diary")
                    st.rerun()

        if dash_btn_calc:
            if not dash_quick_text.strip():
                st.warning("Ketikkan nama menu makanan terlebih dahulu")
            else:
                g_err = _analyze_and_open_text_preview(dash_quick_text, api_key, origin_tab="diary")
                if g_err is not None:
                    _render_guardrail_rejection_card(g_err)

    if st.session_state.get("nutrition_data"):
        if st.session_state.get("preview_origin_tab") == "diary":
            render_nutrition_preview_card("diary", current_user, active_diary_date_str, user_tz, is_admin)
        else:
            st.info(f"Preview terbuka untuk {st.session_state['nutrition_data'].get('dish_name')} di tab {st.session_state.get('preview_origin_tab', 'scanner').title()}")

    # Pelacak Hidrasi & Berat Badan (Ritme 2 Kolom Sejajar)
    water_data = dash_bundle.get("water_data") or {"glasses": 0, "target": 8, "ml": 0}
    water_pct = max(0.0, min(1.0, water_data["glasses"] / max(1, water_data["target"])))

    c_track1, c_track2 = st.columns([1.15, 1], gap="medium")
    with c_track1:
        with st.container(border=True):
            col_w1, col_w3 = st.columns([2.1, 1], vertical_alignment="center")
            with col_w1:
                st.markdown(
                    f'<div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px;">'
                    f'<span style="font-size:0.875rem; font-weight:500; color:var(--text-primary);">Air minum</span>'
                    f'<span class="nc-mono" style="font-size:0.84rem; color:var(--text-secondary);">{water_data["glasses"]}/{water_data["target"]} gelas · {water_data["ml"]} ml</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                st.progress(water_pct)
                st.caption("Target 8 gelas (2.000 ml) per hari")
            with col_w3:
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("+1", width="stretch", key="btn_add_water", help="Tambah 1 gelas air"):
                        log_water_intake(st.session_state["user"]["user_id"], 1, tz_offset=user_tz)
                        _mark_db_mutated()
                        st.toast("Ditambahkan 1 gelas air")
                        st.rerun()
                with col_b2:
                    if st.button("-1", width="stretch", key="btn_sub_water", help="Kurangi 1 gelas air"):
                        log_water_intake(st.session_state["user"]["user_id"], -1, tz_offset=user_tz)
                        _mark_db_mutated()
                        st.rerun()

    with c_track2:
        with st.container(border=True):
            w_hist = dash_bundle.get("weight_history") or []
            latest_w = w_hist[-1]["weight_kg"] if w_hist else float(current_user.get("weight_kg") or 65.0)
            cw_1, cw_2 = st.columns([1.8, 1.1], vertical_alignment="bottom")
            with cw_1:
                in_w = st.number_input("Berat badan hari ini (kg)", min_value=20.0, max_value=250.0, value=float(latest_w), step=0.1, key="dash_weight_in")
            with cw_2:
                if st.button("Catat BB", width="stretch", key="btn_save_weight"):
                    log_weight_entry(st.session_state["user"]["user_id"], in_w, tz_offset=user_tz, recorded_date=active_diary_date_str)
                    st.session_state["user"]["weight_kg"] = in_w
                    _mark_db_mutated()
                    st.toast(f"Berat badan {in_w:.1f} kg disimpan")
                    st.rerun()
            if len(w_hist) >= 2:
                delta_w = round(w_hist[-1]["weight_kg"] - w_hist[0]["weight_kg"], 1)
                sign_w = "+" if delta_w > 0 else ""
                st.caption(f"Tercatat {len(w_hist)} kali · Perubahan vs awal: {sign_w}{delta_w} kg ({w_hist[0]['weight_kg']} ke {w_hist[-1]['weight_kg']} kg)")
            else:
                st.caption("Catat berat badan 1 sampai 2 kali seminggu untuk melihat tren")

    if w_hist and len(w_hist) >= 2:
        with st.expander("Grafik progres berat badan", expanded=False):
            df_w = pd.DataFrame(w_hist)
            df_w["recorded_date"] = pd.to_datetime(df_w["recorded_date"]).dt.strftime("%d/%m")
            st.line_chart(df_w.set_index("recorded_date")["weight_kg"], color="#0369a1")

    # MOMENT 2: Grafik 7 Hari vs Target (Kiri Lebar) & Buku Besar 30 Hari (Kanan Ringkas)
    col_week, col_month = st.columns([1.65, 1], gap="large")

    with col_week:
        st.markdown('<div class="nc-section-title">Asupan 7 hari dibanding target harian</div>', unsafe_allow_html=True)
        if stats["weekly_data"]:
            weekly_svg = _render_weekly_intake_svg(stats["weekly_data"], target_kcal, active_diary_date_str)
            df_week = pd.DataFrame(stats["weekly_data"])
            avg_weekly_kcal = float(df_week["total_kcal"].mean())
            daily_diff = avg_weekly_kcal - target_kcal
            weekly_weight_change = (daily_diff * 7) / 7700.0

            if daily_diff < -100:
                proj_dot = "var(--positive)"
                proj_txt = f"Rata-rata {avg_weekly_kcal:,.0f} kkal/hari (defisit {abs(daily_diff):,.0f} kkal vs target, estimasi -{abs(weekly_weight_change):.2f} kg/minggu)"
            elif daily_diff > 100:
                proj_dot = "var(--warning)"
                proj_txt = f"Rata-rata {avg_weekly_kcal:,.0f} kkal/hari (surplus +{daily_diff:,.0f} kkal vs target, estimasi +{weekly_weight_change:.2f} kg/minggu)"
            else:
                proj_dot = "var(--accent)"
                proj_txt = f"Rata-rata {avg_weekly_kcal:,.0f} kkal/hari, seimbang mendekati target harian"

            st.markdown(
                f'<div class="nc-card">'
                f'{weekly_svg}'
                f'<div style="display:flex; align-items:center; gap:8px; margin-top:12px; padding-top:12px; border-top:1px solid var(--border-col); font-size:0.84rem; color:var(--text-secondary);">'
                f'<span class="nc-meta-dot" style="background:{proj_dot};"></span>'
                f'<span>{proj_txt}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="nc-card" style="padding:24px; text-align:center; color:var(--text-muted); font-size:0.875rem;">'
                'Belum ada catatan makan dalam 7 hari terakhir. Mulai catat melalui kotak di atas atau tab Catat.'
                '</div>',
                unsafe_allow_html=True,
            )

    with col_month:
        st.markdown('<div class="nc-section-title">Ringkasan 30 hari</div>', unsafe_allow_html=True)
        m_data = stats["monthly_summary"]
        avg_30 = m_data["total_kcal"] / max(1, m_data["active_days"])
        st.markdown(
            f'<div class="nc-card">'
            f'  <div class="nc-label">Total kalori 30 hari</div>'
            f'  <div class="nc-mono" style="font-size:1.75rem; font-weight:500; margin:6px 0 12px 0; color:var(--text-primary);">'
            f'    {m_data["total_kcal"]:,.0f} <span style="font-size:0.9rem; font-weight:400; color:var(--text-muted);">kkal</span>'
            f'  </div>'
            f'  <div class="nc-ledger-row"><span style="color:var(--text-secondary);">Hari aktif mencatat</span><span class="nc-mono" style="font-weight:500;">{m_data["active_days"]} hari</span></div>'
            f'  <div class="nc-ledger-row"><span style="color:var(--text-secondary);">Total menu masuk</span><span class="nc-mono" style="font-weight:500;">{m_data["total_meals"]} porsi</span></div>'
            f'  <div class="nc-ledger-row"><span style="color:var(--text-secondary);">Rata-rata hari aktif</span><span class="nc-mono" style="font-weight:500;">{avg_30:,.0f} kkal</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Riwayat Makan Hari Ini
    st.markdown('<div class="nc-section-title">Catatan makan hari ini</div>', unsafe_allow_html=True)

    dup_ids = find_duplicate_meals(stats["today_meals"])
    if dup_ids:
        c_dup1, c_dup2 = st.columns([2.6, 1.4], vertical_alignment="center")
        with c_dup1:
            st.warning(f"Terdeteksi {len(dup_ids)} catatan menu kembar pada tanggal ini")
        with c_dup2:
            if st.button(f"Rapikan menu kembar ({len(dup_ids)})", type="primary", width="stretch", key="btn_clean_dups"):
                del_cnt = remove_duplicate_meals_for_date(st.session_state["user"]["user_id"], active_diary_date_str)
                _mark_db_mutated()
                st.toast(f"{del_cnt} catatan kembar dirapikan")
                st.rerun()

    yest_for_copy = (active_diary_date - timedelta(days=1)).strftime("%Y-%m-%d")

    if stats["today_meals"]:
        wa_text = format_whatsapp_daily_report(
            display_name=current_user["display_name"],
            diary_date=active_diary_date,
            today_kcal=today_kcal,
            target_kcal=target_kcal,
            pct_actual=pct_today_actual,
            today_totals=stats["today_totals"],
            today_meals=stats["today_meals"],
        )
        wa_encoded = urllib.parse.quote(wa_text)
        wa_url = f"https://api.whatsapp.com/send?text={wa_encoded}"

        col_share1, col_share2 = st.columns([1, 1])
        with col_share1:
            st.markdown(
                f'<a href="{wa_url}" target="_blank" style="text-decoration:none; display:block;">'
                f'<div style="background:var(--bg-card); color:var(--text-primary); border:1px solid var(--border-col); padding:8px 16px; min-height:38px; border-radius:8px; font-weight:500; font-size:0.875rem; display:flex; align-items:center; justify-content:center; gap:8px;">'
                f'{_lucide_svg("share", 16)}<span>Bagikan laporan ke WhatsApp</span>'
                f'</div></a>',
                unsafe_allow_html=True,
            )

        with col_share2:
            df_export = pd.DataFrame(stats["today_meals"])
            if not df_export.empty:
                cols_to_export = [c for c in ["logged_at", "meal_type", "dish_name", "energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "sodium_mg", "photo_caption"] if c in df_export.columns]
                safe_df = df_export[cols_to_export].copy()
                for txt_col in ("logged_at", "meal_type", "dish_name", "photo_caption"):
                    if txt_col in safe_df.columns:
                        safe_df[txt_col] = safe_df[txt_col].map(lambda v: sanitize_csv_cell(v) if isinstance(v, str) else v)
                csv_data = safe_df.to_csv(index=False).encode('utf-8')
                st.download_button("Unduh rekap CSV", data=csv_data, file_name=f"nutrisi_harian_{active_diary_date.strftime('%Y%m%d')}.csv", mime="text/csv", width="stretch")

        st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

        MEAL_ORDER = [
            ("Sarapan", "Sarapan"),
            ("Makan Siang", "Makan Siang"),
            ("Makan Malam", "Makan Malam"),
            ("Camilan", "Camilan & Minuman"),
        ]

        grouped_meals = {}
        for m in stats["today_meals"]:
            mtype = _normalize_meal_key(m.get("meal_type"))
            if mtype not in grouped_meals:
                grouped_meals[mtype] = []
            grouped_meals[mtype].append(m)

        ordered_keys = [k for k, _ in MEAL_ORDER if k in grouped_meals]
        for k in grouped_meals:
            if k not in ordered_keys:
                ordered_keys.append(k)

        EDIT_MEAL_CHOICES = ["Sarapan", "Makan Siang", "Makan Malam", "Camilan"]

        for mtype in ordered_keys:
            meals_in_group = grouped_meals[mtype]
            subtotal_kcal = sum(x["energy_kcal"] for x in meals_in_group)
            subtotal_p = sum(x["protein_g"] for x in meals_in_group)
            subtotal_f = sum(x["fat_g"] for x in meals_in_group)
            subtotal_c = sum(x["carb_g"] for x in meals_in_group)

            label_display = dict(MEAL_ORDER).get(mtype, mtype)

            with st.container(border=True):
                c_mhead1, c_mhead2 = st.columns([2, 1.2], vertical_alignment="center")
                with c_mhead1:
                    st.markdown(f'<div style="font-size:0.95rem; font-weight:600; color:var(--text-primary);">{sanitize_html_text(label_display)}</div>', unsafe_allow_html=True)
                with c_mhead2:
                    st.markdown(
                        f'<div class="nc-mono" style="text-align:right; font-weight:500; font-size:0.95rem; color:var(--accent);">{subtotal_kcal:,.1f} kkal</div>'
                        f'<div class="nc-mono" style="text-align:right; font-size:0.75rem; color:var(--text-muted);">P {subtotal_p:.1f}g · L {subtotal_f:.1f}g · K {subtotal_c:.1f}g</div>',
                        unsafe_allow_html=True,
                    )

                st.markdown("<div style='height: 8px; border-bottom: 1px solid var(--border-col); margin-bottom: 8px;'></div>", unsafe_allow_html=True)

                for m in meals_in_group:
                    try:
                        time_str = datetime.strptime(m["logged_at"][:19], "%Y-%m-%d %H:%M:%S").strftime("%H:%M") if " " in str(m["logged_at"]) else str(m["logged_at"])
                    except Exception:
                        time_str = str(m["logged_at"])[11:16] or str(m["logged_at"])
                    is_just_saved = ("last_saved_item" in st.session_state and st.session_state["last_saved_item"] and st.session_state["last_saved_item"].get("id") == m["id"])
                    saved_tag = ' <span class="nc-badge" style="margin-left:6px;"><span class="nc-meta-dot" style="background:var(--positive);"></span>Baru disimpan</span>' if is_just_saved else ''

                    col_row1, col_row2, col_row3, col_row4 = st.columns([2.9, 1.9, 0.65, 0.65], vertical_alignment="center")
                    with col_row1:
                        mult_lbl = f" · {m.get('portion_multiplier', 1.0)}x" if float(m.get("portion_multiplier") or 1.0) != 1.0 else ""
                        cap_suffix = f" · {sanitize_html_text(m['photo_caption'])}" if m['photo_caption'] else ""
                        st.markdown(
                            f'<div style="font-size:0.9rem; font-weight:500; color:var(--text-primary);">{sanitize_html_text(m["dish_name"])}'
                            f'<span class="nc-mono" style="font-size:0.8rem; color:var(--text-muted);">{mult_lbl}</span>{saved_tag}</div>'
                            f'<div class="nc-mono" style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">{time_str}{cap_suffix}</div>',
                            unsafe_allow_html=True,
                        )
                    with col_row2:
                        st.markdown(
                            f'<div class="nc-mono" style="text-align:right; font-size:0.9rem; font-weight:500; color:var(--text-primary);">{m["energy_kcal"]:,.1f} kkal</div>'
                            f'<div class="nc-mono" style="text-align:right; font-size:0.75rem; color:var(--text-muted);">P {m["protein_g"]}g · L {m["fat_g"]}g · K {m["carb_g"]}g</div>',
                            unsafe_allow_html=True,
                        )
                    with col_row3:
                        with st.popover("", icon=":material/edit:", width="stretch", help="Ubah waktu makan atau porsi"):
                            st.markdown(f"**Edit: {m['dish_name']}**")
                            cur_mt = _normalize_meal_key(m.get("meal_type"))
                            mt_idx = EDIT_MEAL_CHOICES.index(cur_mt) if cur_mt in EDIT_MEAL_CHOICES else 1
                            ed_mt = st.selectbox("Waktu makan", EDIT_MEAL_CHOICES, index=mt_idx, key=f"ed_mt_{m['id']}")
                            cur_mult = _closest_portion_opt(m.get("portion_multiplier") or 1.0)
                            ed_mult = st.select_slider(
                                "Ukuran porsi",
                                options=PORTION_OPTIONS,
                                value=cur_mult,
                                format_func=lambda x: PORTION_LABELS[x],
                                key=f"ed_mult_{m['id']}"
                            )
                            if st.button("Simpan perubahan", type="primary", width="stretch", key=f"btn_ed_save_{m['id']}"):
                                try:
                                    res_sc = scale_meal_log_portion(m["id"], st.session_state["user"]["user_id"], ed_mult, new_meal_type=ed_mt)
                                    if res_sc:
                                        st.session_state["last_saved_item"] = res_sc
                                    _mark_db_mutated()
                                    st.toast(f"{m['dish_name']} diperbarui ({ed_mt}, {ed_mult}x)")
                                    st.rerun()
                                except FoodGuardrailRejected as g_err:
                                    _render_guardrail_rejection_card(g_err)
                    with col_row4:
                        if st.button("", icon=":material/delete:", key=f"del_{m['id']}", help="Hapus menu ini", width="stretch"):
                            delete_meal_log(m["id"], st.session_state["user"]["user_id"])
                            _mark_db_mutated()
                            st.toast("Catatan makanan dihapus")
                            st.rerun()
    else:
        st.markdown(
            f'<div class="nc-card" style="padding:32px 20px; text-align:center;">'
            f'<div style="color:var(--text-muted); margin-bottom:8px;">{_lucide_svg("utensils", 24)}</div>'
            f'<div style="font-weight:500; font-size:0.95rem; color:var(--text-primary); margin-bottom:4px;">Belum ada catatan makan hari ini</div>'
            f'<div style="font-size:0.84rem; color:var(--text-muted); max-width:420px; margin:0 auto; line-height:1.5;">'
            f'Ketik menu di kotak Catat Cepat, salin daftar kemarin, atau buka tab Catat untuk memotret makanan.'
            f'</div></div>',
            unsafe_allow_html=True,
        )
        if st.button("Salin daftar menu dari kemarin", width="stretch", key="btn_copy_yesterday_empty"):
            cnt_cp = copy_meals_from_date(st.session_state["user"]["user_id"], yest_for_copy, active_diary_date_str, tz_offset=user_tz)
            if cnt_cp > 0:
                _mark_db_mutated()
                st.toast(f"{cnt_cp} menu disalin dari kemarin ({yest_for_copy})")
                st.rerun()
            else:
                st.info("Belum ada catatan makan kemarin untuk disalin")

# ================= TAB 2: CATAT MAKANAN BARU (3 SUB-TAB RINGKAS) =================
with tab_scanner:
    if not api_key:
        st.warning("Mode offline lab aktif (API Key belum disetel di Streamlit Secrets)")
        st.info("Pencarian database lab (1.304 pangan), scan barcode, dan input manual tetap berfungsi penuh. Tambahkan GEMINI_API_KEY di Secrets untuk mengaktifkan analisis foto.")

    subtab_foto, subtab_teks, subtab_barcode = st.tabs([
        "Foto Piring",
        "Ketik & Menu Cepat",
        "Barcode & Manual"
    ])

    with subtab_foto:
        st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:4px;">Foto makanan dari galeri atau kamera</div>', unsafe_allow_html=True)
        st.caption("Di ponsel Android atau iPhone, pilih Browse files untuk langsung mengambil foto dari kamera atau galeri")
        if st.session_state.get("scanner_guardrail_notice") and st.session_state["scanner_guardrail_notice"][0] == "foto":
            _, r_type, r_msg = st.session_state.pop("scanner_guardrail_notice")
            _render_guardrail_rejection_card(FoodGuardrailRejected(r_type, r_msg))

        c_up1, c_up2 = st.columns([1.2, 1], gap="large")
        with c_up1:
            up_file = st.file_uploader("Pilih atau jepret foto piring makanan", type=["jpg", "jpeg", "png", "webp"], key="scan_foto")
            with st.expander("Buka kamera langsung di browser", expanded=False):
                cam_file = st.camera_input("Arahkan kamera ke piring makanan")

            active_img_file = up_file or cam_file
            im = _safe_open_uploaded_image(active_img_file) if active_img_file else None
            if im is not None:
                st.image(im, caption="Foto siap dianalisis", width="stretch")
                p_caption = st.text_input("Catatan atau keterangan (opsional)", placeholder="Bumbu kacang dipisah, atau ayam tanpa kulit", max_chars=160, key="f_cap")
            else:
                p_caption = ""
        with c_up2:
            if im is not None:
                st.markdown('<div style="font-size:1.05rem; font-weight:600; margin-bottom:4px;">Siap dianalisis</div>', unsafe_allow_html=True)
                st.caption("Sistem memindai porsi perorangan URT dan mencocokkan ke 1.304 data lab TKPI Kemenkes. Hasil tampil sebagai Preview sebelum disimpan.")

                if not scan_status["can_scan"]:
                    _render_scan_quota_exhausted_notice(current_user, scan_status)
                else:
                    if st.button("Hitung gizi foto", type="primary", width="stretch", key="btn_foto"):
                        _execute_vision_scan_and_open_preview(
                            img_obj=im,
                            prompt_caption=p_caption,
                            notice_channel="foto",
                            active_user=current_user,
                            tz_offset=user_tz,
                            api_key_val=api_key,
                            sc_status=scan_status,
                            spinner_text="Menganalisis foto makanan...",
                            user_caption=p_caption or "Foto Piring",
                            toast_msg="Foto dianalisis. Periksa porsi dan waktu makan sebelum disimpan",
                        )
            else:
                st.markdown(
                    '<div class="nc-note-box">'
                    '<span class="nc-meta-dot" style="background:var(--accent); margin-top:7px;"></span>'
                    '<div>Potret piring dari atas pada pencahayaan terang agar nasi, lauk, dan sayuran terlihat jelas dalam satu bingkai.</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

    with subtab_teks:
        st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:4px;">Ketik menu makanan atau pilih menu cepat</div>', unsafe_allow_html=True)
        t_input = st.text_area("Menu makanan", placeholder="1 piring gado-gado lontong dengan telur rebus dan bumbu kacang", height=90, max_chars=200)
        if st.button("Hitung nutrisi menu", type="primary", width="stretch", key="btn_teks"):
            if not t_input.strip():
                st.warning("Tulis menu makanan terlebih dahulu")
            else:
                g_err = _analyze_and_open_text_preview(t_input, api_key, origin_tab="scanner")
                if g_err is not None:
                    _render_guardrail_rejection_card(g_err)

        st.markdown("---")
        st.caption("Menu cepat Indonesia")
        PRESET_MENUS = [
            ("Nasi Goreng Telur", "Nasi Goreng + Telur Ceplok", 180.0, 485.0, 16.5, 18.0, 62.0, 2.2),
            ("Ayam Geprek + Nasi", "Nasi Putih + Ayam Geprek Sambal", 250.0, 560.0, 29.0, 24.0, 56.0, 2.0),
            ("Soto Ayam + Nasi", "Soto Ayam Kuah Bening + Nasi Putih", 300.0, 395.0, 22.0, 11.5, 49.0, 1.8),
            ("Pecel Lele + Nasi", "Nasi Putih + Lele Goreng + Lalapan", 240.0, 430.0, 24.5, 16.0, 46.0, 2.5),
            ("Sate Ayam 10 Tusuk", "Sate Ayam 10 Tusuk + Bumbu Kacang", 180.0, 365.0, 31.0, 19.5, 16.0, 1.5),
            ("Pisang + Susu", "1 Buah Pisang Ambon + 1 Gelas Susu", 250.0, 235.0, 8.5, 6.0, 37.0, 2.8),
        ]
        pm_cols = st.columns(3)
        for idx_pm, (pm_btn, pm_title, pm_w, pm_k, pm_p, pm_f, pm_c, pm_fib) in enumerate(PRESET_MENUS):
            with pm_cols[idx_pm % 3]:
                if st.button(pm_btn, width="stretch", key=f"pm_fast_{idx_pm}"):
                    scale_pm = 100.0 / float(pm_w)
                    _open_food_preview({
                        "dish_name": pm_title,
                        "confidence": "high",
                        "portion_category": "1 porsi standar",
                        "serving_reference": f"1 porsi standar (~{pm_w:.0f}g)",
                        "source_origin": "Standar Lab TKPI Kemenkes RI",
                        "components": [{
                            "name": pm_title,
                            "weight_g": float(pm_w),
                            "energy_kcal_per_100g": round(pm_k * scale_pm, 4),
                            "protein_g_per_100g": round(pm_p * scale_pm, 4),
                            "fat_g_per_100g": round(pm_f * scale_pm, 4),
                            "carb_g_per_100g": round(pm_c * scale_pm, 4),
                            "fiber_g_per_100g": round(pm_fib * scale_pm, 4),
                            "sodium_mg_per_100g": round(320.0 * scale_pm, 4),
                            "custom_override": True,
                            "source_label": "Standar Lab TKPI Kemenkes RI"
                        }],
                        "health_tip": "Atur porsi dan sesi makan lalu simpan ke buku harian."
                    }, origin_tab="scanner")
                    st.rerun()

    with subtab_barcode:
        st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:4px;">Cek barcode kemasan & input manual</div>', unsafe_allow_html=True)
        st.caption("Ketik nomor barcode EAN-13 atau pilih salah satu contoh produk lokal")

        c_bar1, c_bar2 = st.columns([2.2, 1], vertical_alignment="bottom")
        with c_bar1:
            in_barcode = st.text_input(
                "Nomor barcode produk (8 sampai 14 digit)",
                placeholder="8998866200231 atau 089686010921",
                key="input_barcode_field"
            )
        with c_bar2:
            btn_barcode = st.button("Cek barcode", type="primary", width="stretch", key="btn_check_barcode")

        st.caption("Contoh produk kemasan")
        sc_b1, sc_b2, sc_b3, sc_b4 = st.columns(4)
        sample_code = None
        if sc_b1.button("Ultra Milk 250ml", width="stretch", key="smp_bc1"):
            sample_code = "8998866200231"
        if sc_b2.button("Indomie Goreng", width="stretch", key="smp_bc2"):
            sample_code = "089686010921"
        if sc_b3.button("Nutella 15g", width="stretch", key="smp_bc3"):
            sample_code = "3017620422003"
        if sc_b4.button("Oreo Vanilla", width="stretch", key="smp_bc4"):
            sample_code = "7622210449283"

        target_bc = sample_code or (in_barcode.strip() if btn_barcode else "")
        if target_bc:
            with st.spinner(f"Mencari barcode {target_bc}..."):
                matched = find_best_match(target_bc)
            if matched:
                src_info = matched.get("source_origin") or "Katalog Terverifikasi Lokal"
                _open_food_preview({
                    "dish_name": matched["food_name"],
                    "confidence": "high",
                    "portion_category": "standar kemasan",
                    "serving_reference": matched.get("serving_unit") or "1 kemasan",
                    "barcode": matched.get("barcode") or target_bc,
                    "source_origin": src_info,
                    "serving_unit": matched.get("serving_unit") or "1 kemasan",
                    "components": [{
                        "name": matched["food_name"],
                        "weight_g": matched.get("default_serving_weight") or 100.0,
                        "energy_kcal_per_100g": matched["energy_kcal"],
                        "protein_g_per_100g": matched["protein_g"],
                        "fat_g_per_100g": matched["fat_g"],
                        "carb_g_per_100g": matched["carb_g"],
                        "fiber_g_per_100g": matched.get("fiber_g") or 0.0,
                        "sodium_mg_per_100g": matched.get("sodium_mg") or 0.0,
                        "custom_override": True,
                        "source_label": src_info
                    }],
                    "health_tip": f"Sumber data: {src_info}. Takaran saji: {matched.get('serving_unit', '100g')}."
                }, origin_tab="scanner")
                st.toast(f"Produk ditemukan: {matched['food_name']}")
                st.rerun()
            else:
                st.error("Nomor barcode tidak ditemukan. Gunakan Foto Label Gizi atau Input Manual di bawah")

        if st.session_state.get("scanner_guardrail_notice") and st.session_state["scanner_guardrail_notice"][0] == "pkg":
            _, r_type, r_msg = st.session_state.pop("scanner_guardrail_notice")
            _render_guardrail_rejection_card(FoodGuardrailRejected(r_type, r_msg))

        with st.expander("Scan foto tabel informasi nilai gizi kemasan", expanded=False):
            pkg_file = st.file_uploader("Pilih foto bungkus atau label gizi kemasan", type=["jpg", "jpeg", "png", "webp"], key="scan_pkg_img")
            if pkg_file:
                im_pkg = _safe_open_uploaded_image(pkg_file)
                if im_pkg is not None:
                    st.image(im_pkg, caption="Foto kemasan / label gizi", width=260)
                    if not scan_status["can_scan"]:
                        _render_scan_quota_exhausted_notice(current_user, scan_status)
                    elif not api_key:
                        st.warning("Vision AI belum aktif karena GEMINI_API_KEY belum disetel")
                    elif st.button("Ekstrak tabel nilai gizi", type="primary", key="btn_scan_pkg"):
                        _execute_vision_scan_and_open_preview(
                            img_obj=im_pkg,
                            prompt_caption="Kemasan produk ritel / tabel informasi nilai gizi",
                            notice_channel="pkg",
                            active_user=current_user,
                            tz_offset=user_tz,
                            api_key_val=api_key,
                            sc_status=scan_status,
                            spinner_text="Membaca tabel nilai gizi pada kemasan...",
                            source_origin="Ekstraksi Vision Label Gizi",
                            toast_msg="Label gizi kemasan diekstrak. Periksa porsi sebelum disimpan",
                        )

        with st.expander("Input manual makanan atau resep sendiri", expanded=False):
            col_m1, col_m2 = st.columns([1.4, 1], gap="large")
            with col_m1:
                m_food_name = st.text_input("Nama makanan atau produk", placeholder="Susu Ultra Milk Cokelat 250ml", max_chars=80)
                m_serving = st.text_input("Ukuran porsi", placeholder="1 kotak (250ml)", max_chars=50)
                col_nut1, col_nut2 = st.columns(2)
                with col_nut1:
                    m_kcal = st.number_input("Total kalori (kkal)", min_value=0.0, max_value=3500.0, value=160.0, step=10.0)
                    m_prot = st.number_input("Protein (g)", min_value=0.0, max_value=200.0, value=8.0, step=1.0)
                with col_nut2:
                    m_fat = st.number_input("Lemak (g)", min_value=0.0, max_value=200.0, value=4.0, step=1.0)
                    m_carb = st.number_input("Karbohidrat (g)", min_value=0.0, max_value=400.0, value=24.0, step=1.0)

                MEAL_MAP_MANUAL = {
                    "Sarapan": "Sarapan",
                    "Makan Siang": "Makan Siang",
                    "Makan Malam": "Makan Malam",
                    "Camilan": "Camilan"
                }
                m_meal_label = st.selectbox("Waktu makan", list(MEAL_MAP_MANUAL.keys()), key="sel_manual_time")
                m_meal_clean = MEAL_MAP_MANUAL[m_meal_label]

                if st.button("Simpan ke buku harian", type="primary", width="stretch"):
                    if m_food_name.strip():
                        try:
                            clean_manual_name = validate_food_candidate(
                                m_food_name.strip(), m_kcal, m_prot, m_fat, m_carb, is_catalog_entry=False
                            )
                            res_log = log_meal(
                                user_id=st.session_state["user"]["user_id"],
                                dish_name=clean_manual_name,
                                totals={"energy_kcal": m_kcal, "protein_g": m_prot, "fat_g": m_fat, "carb_g": m_carb, "fiber_g": 0.0, "sodium_mg": 0.0},
                                multiplier=1.0,
                                caption=f"Manual Input ({m_serving})",
                                meal_type=m_meal_clean,
                                log_date=active_diary_date_str,
                                tz_offset=user_tz
                            )
                            st.session_state["last_saved_item"] = res_log
                            add_custom_food(st.session_state["user"]["user_id"], clean_manual_name, m_serving, m_kcal, m_prot, m_fat, m_carb)
                            st.success(f"Tercatat ke sesi {m_meal_clean}")
                            _mark_db_mutated()
                            st.rerun()
                        except FoodGuardrailRejected as g_err:
                            _render_guardrail_rejection_card(g_err)
                    else:
                        st.warning("Isi nama makanan terlebih dahulu")

            with col_m2:
                st.markdown('<div style="font-size:0.9rem; font-weight:600; margin-bottom:8px;">Koleksi tersimpan</div>', unsafe_allow_html=True)
                saved_custom = _fetch_custom_foods_cached(st.session_state["user"]["user_id"], st.session_state.get("db_mutation_ver", 0))
                if saved_custom:
                    for c_item in saved_custom:
                        with st.container(border=True):
                            st.markdown(f"**{c_item['food_name']}** ({c_item['serving_size']})")
                            st.caption(f"{c_item['energy_kcal']} kkal · P {c_item['protein_g']}g · L {c_item['fat_g']}g · K {c_item['carb_g']}g")
                            col_cbtn1, col_cbtn2 = st.columns([2.4, 0.8])
                            with col_cbtn1:
                                if st.button("Catat lagi", key=f"quick_log_{c_item['id']}", width="stretch"):
                                    try:
                                        res_log = log_meal(
                                            user_id=st.session_state["user"]["user_id"],
                                            dish_name=c_item["food_name"],
                                            totals={"energy_kcal": c_item["energy_kcal"], "protein_g": c_item["protein_g"], "fat_g": c_item["fat_g"], "carb_g": c_item["carb_g"], "fiber_g": 0.0, "sodium_mg": 0.0},
                                            multiplier=1.0,
                                            caption="Koleksi Pribadi",
                                            meal_type=m_meal_clean,
                                            log_date=active_diary_date_str,
                                            tz_offset=user_tz
                                        )
                                        st.session_state["last_saved_item"] = res_log
                                        _mark_db_mutated()
                                        st.toast(f"{c_item['food_name']} tercatat")
                                        st.rerun()
                                    except FoodGuardrailRejected as g_err:
                                        _render_guardrail_rejection_card(g_err)
                            with col_cbtn2:
                                if st.button("", icon=":material/delete:", key=f"del_c_{c_item['id']}", help="Hapus item", width="stretch"):
                                    delete_custom_food(c_item["id"], st.session_state["user"]["user_id"])
                                    _mark_db_mutated()
                                    st.rerun()
                else:
                    st.caption("Makanan manual yang disimpan akan muncul di sini untuk pencatatan ulang.")

    # Kartu Preview Tunggal Anti-Double + Mini-Rekap Hari Ini
    if st.session_state.get("nutrition_data"):
        if st.session_state.get("preview_origin_tab", "scanner") == "scanner":
            st.markdown("---")
            render_nutrition_preview_card("scanner", current_user, active_diary_date_str, user_tz, is_admin)
        else:
            st.info(f"Preview terbuka untuk {st.session_state['nutrition_data'].get('dish_name')} di tab lain")

    st.markdown("---")
    with st.expander(f"Sudah masuk hari ini ({stats['today_totals']['count']} menu · {today_kcal:,.1f} kkal)", expanded=bool(stats["today_meals"])):
        if stats["today_meals"]:
            for mr in stats["today_meals"]:
                mr_c1, mr_c2, mr_c3 = st.columns([3.2, 1.4, 0.6], vertical_alignment="center")
                with mr_c1:
                    st.markdown(f"**{mr['dish_name']}** · `{_normalize_meal_key(mr.get('meal_type'))}`")
                with mr_c2:
                    st.markdown(f'<div class="nc-mono" style="text-align:right; font-size:0.84rem; color:var(--text-secondary);">{mr["energy_kcal"]:,.1f} kkal</div>', unsafe_allow_html=True)
                with mr_c3:
                    if st.button("", icon=":material/delete:", key=f"mini_del_{mr['id']}", help="Hapus dari hari ini", width="stretch"):
                        delete_meal_log(mr["id"], st.session_state["user"]["user_id"])
                        _mark_db_mutated()
                        st.toast("Catatan dihapus")
                        st.rerun()
        else:
            st.caption("Belum ada makanan yang disimpan pada tanggal ini. Setelah analisis, klik Simpan ke buku harian.")

# ================= TAB 3: SUMBER DATA & ENSIKLOPEDIA NUTRISI =================
with tab_sources:
    st.markdown('<div style="font-size:1.35rem; font-weight:600; margin-bottom:4px; color:var(--text-primary);">Rujukan pangkalan data nutrisi</div>', unsafe_allow_html=True)
    st.caption("Seluruh kalkulasi nilai nutrisi berpatokan pada data uji laboratorium TKPI Kemenkes RI, USDA FoodData Central, dan Open Food Facts")

    if is_admin:
        pending_list = _fetch_pending_foods_cached("pending", st.session_state.get("db_mutation_ver", 0))
        with st.expander(f"Panel kurasi data gizi sebelum publikasi ({len(pending_list)} draft menunggu, Admin)", expanded=bool(len(pending_list) > 0)):
            st.caption("Data baru dari Open Food Facts, auto-learn, dan usulan pengguna masuk ke ruang tinjauan sebelum dipublikasikan ke katalog utama.")
            if pending_list:
                for p_item in pending_list[:15]:
                    with st.container(border=True):
                        st.markdown(f"**Draft #{p_item['id']}: {p_item['food_name']}** · `{p_item['source_origin']}`")
                        pc1, pc2, pc3 = st.columns([2, 2, 1.2])
                        with pc1:
                            p_name = st.text_input("Nama pangan", value=p_item["food_name"], key=f"pend_n_{p_item['id']}")
                            p_cat = st.text_input("Kategori", value=p_item["category"] or "Produk Kemasan", key=f"pend_cat_{p_item['id']}")
                            p_bc = st.text_input("Barcode", value=p_item["barcode"] or "", key=f"pend_bc_{p_item['id']}")
                        with pc2:
                            p_kcal = st.number_input("Energi (kkal/100g)", value=float(p_item["energy_kcal"]), step=5.0, key=f"pend_k_{p_item['id']}")
                            p_prot = st.number_input("Protein (g/100g)", value=float(p_item["protein_g"]), step=0.5, key=f"pend_p_{p_item['id']}")
                            p_fat = st.number_input("Lemak (g/100g)", value=float(p_item["fat_g"]), step=0.5, key=f"pend_f_{p_item['id']}")
                            p_carb = st.number_input("Karbo (g/100g)", value=float(p_item["carb_g"]), step=0.5, key=f"pend_c_{p_item['id']}")
                        with pc3:
                            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
                            if st.button("Publikasikan", type="primary", width="stretch", key=f"btn_pub_{p_item['id']}"):
                                try:
                                    publish_food_to_catalog(
                                        food_name=p_name, category=p_cat,
                                        kcal_100=p_kcal, p_100=p_prot, f_100=p_fat, c_100=p_carb,
                                        fib_100=float(p_item.get("fiber_g") or 0.0),
                                        sod_100=float(p_item.get("sodium_mg") or 0.0),
                                        barcode=p_bc,
                                        serving_unit=p_item.get("serving_unit") or "100g",
                                        serving_weight=float(p_item.get("default_serving_weight") or 100.0),
                                        pending_id=p_item["id"]
                                    )
                                    _fetch_tkpi_categories_and_count.clear()
                                    _search_tkpi_catalog_cached.clear()
                                    _mark_db_mutated()
                                    st.toast(f"{p_name} dipublikasikan ke katalog utama")
                                    st.rerun()
                                except FoodGuardrailRejected as g_err:
                                    _render_guardrail_rejection_card(g_err)
                            if st.button("Tolak draft", width="stretch", key=f"btn_rej_{p_item['id']}"):
                                reject_pending_food(p_item["id"])
                                _mark_db_mutated()
                                st.toast("Draft dihapus dari antrean")
                                st.rerun()
            else:
                st.info("Tidak ada antrean draft yang menunggu.")

            st.markdown("---")
            st.markdown('<div style="font-size:0.9rem; font-weight:600; margin-bottom:8px;">Tambah atau edit pangan ke katalog utama</div>', unsafe_allow_html=True)
            add_c1, add_c2, add_c3 = st.columns(3)
            with add_c1:
                new_f_name = st.text_input("Nama makanan atau produk", placeholder="Susu Steril Bear Brand", key="new_cat_name")
                new_f_cat = st.text_input("Kategori", value="Produk Ritel Terverifikasi", key="new_cat_cat")
                new_f_bc = st.text_input("Kode barcode (opsional)", placeholder="8992696404441", key="new_cat_bc")
            with add_c2:
                new_f_kcal = st.number_input("Kalori (per 100g)", min_value=0.0, value=120.0, step=5.0, key="new_cat_kcal")
                new_f_p = st.number_input("Protein (g)", min_value=0.0, value=6.0, step=0.5, key="new_cat_p")
                new_f_f = st.number_input("Lemak (g)", min_value=0.0, value=4.5, step=0.5, key="new_cat_f")
            with add_c3:
                new_f_c = st.number_input("Karbohidrat (g)", min_value=0.0, value=9.5, step=0.5, key="new_cat_c")
                new_f_fib = st.number_input("Serat (g)", min_value=0.0, value=0.0, step=0.5, key="new_cat_fib")
                st.markdown("<div style='height: 24px;'></div>", unsafe_allow_html=True)
                if st.button("Simpan ke katalog", type="primary", width="stretch", key="btn_direct_pub"):
                    if new_f_name.strip():
                        try:
                            publish_food_to_catalog(
                                food_name=new_f_name.strip(), category=new_f_cat.strip(),
                                kcal_100=new_f_kcal, p_100=new_f_p, f_100=new_f_f, c_100=new_f_c,
                                fib_100=new_f_fib, barcode=new_f_bc.strip()
                            )
                            _fetch_tkpi_categories_and_count.clear()
                            _search_tkpi_catalog_cached.clear()
                            _mark_db_mutated()
                            st.success(f"{new_f_name} disimpan ke katalog utama")
                            st.rerun()
                        except FoodGuardrailRejected as g_err:
                            _render_guardrail_rejection_card(g_err)
                    else:
                        st.warning("Isi nama makanan terlebih dahulu")

    # 3 Kartu Lembaga Sumber Resmi (Tenang, Seragam, Tanpa Emoji & Warna Pelangi)
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown(
            '<div class="nc-card" style="height:100%;">'
            '<div style="font-size:0.95rem; font-weight:600; color:var(--text-primary);">Kemenkes RI (TKPI)</div>'
            '<p style="font-size:0.84rem; color:var(--text-secondary); margin:8px 0 12px 0; line-height:1.5;">'
            'Tabel Komposisi Pangan Indonesia (Panganku.org) memuat 1.100+ bahan mentah dan masakan nusantara per 100g BDD.'
            '</p>'
            '<a href="https://www.panganku.org" target="_blank" style="font-weight:500; color:var(--accent); font-size:0.84rem; text-decoration:none;">Panganku.org</a>'
            '</div>',
            unsafe_allow_html=True,
        )
    with col_s2:
        st.markdown(
            '<div class="nc-card" style="height:100%;">'
            '<div style="font-size:0.95rem; font-weight:600; color:var(--text-primary);">Open Food Facts & USDA</div>'
            '<p style="font-size:0.84rem; color:var(--text-secondary); margin:8px 0 12px 0; line-height:1.5;">'
            'Pangkalan data terbuka produk kemasan dunia (barcode EAN-13) dan standar laboratorium Departemen Pertanian AS.'
            '</p>'
            '<a href="https://world.openfoodfacts.org" target="_blank" style="font-weight:500; color:var(--accent); font-size:0.84rem; text-decoration:none;">Open Food Facts</a>'
            '</div>',
            unsafe_allow_html=True,
        )
    with col_s3:
        st.markdown(
            '<div class="nc-card" style="height:100%;">'
            '<div style="font-size:0.95rem; font-weight:600; color:var(--text-primary);">NilaiGizi & AKG Kemenkes</div>'
            '<p style="font-size:0.84rem; color:var(--text-secondary); margin:8px 0 12px 0; line-height:1.5;">'
            'Rujukan nutrisionis nasional dan acuan Angka Kecukupan Gizi (Permenkes No. 28/2019) untuk validasi porsi URT.'
            '</p>'
            '<a href="https://nilaigizi.com" target="_blank" style="font-weight:500; color:var(--accent); font-size:0.84rem; text-decoration:none;">NilaiGizi.com</a>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="nc-section-title">Pencarian pangkalan data laboratorium & ritel</div>', unsafe_allow_html=True)
    st.caption("Cari bahan makanan, produk ritel, atau nomor barcode untuk melihat profil gizi per 100 gram")

    col_q1, col_q2 = st.columns([2, 1])
    with col_q1:
        search_query = st.text_input("Cari pangan atau barcode", placeholder="Ayam, nasi, telur, Ultra Milk, Indomie", key="kb_search")
    cats, total_db_count = _fetch_tkpi_categories_and_count()
    with col_q2:
        sel_cat = st.selectbox("Filter kategori", ["Semua Kategori"] + cats, key="kb_cat")

    results = _search_tkpi_catalog_cached(search_query.strip(), sel_cat)

    if results:
        table_kb = []
        for r in results:
            takaran_str = f"{r[9] or '100g'} ({float(r[10] or 100.0):.0f}g)" if r[9] else f"{float(r[10] or 100.0):.0f}g"
            table_kb.append({
                "Nama Pangan": r[0],
                "Kategori": r[1] or "-",
                "Takaran Saji": takaran_str,
                "Energi (kkal/100g)": r[2],
                "Protein (g)": r[3],
                "Lemak (g)": r[4],
                "Karbohidrat (g)": r[5],
                "Serat (g)": r[6],
                "Natrium (mg)": r[7],
                "Barcode": r[8] or "-"
            })
        st.dataframe(table_kb, width="stretch", hide_index=True)
        st.caption(f"Menampilkan {len(results)} hasil teratas dari {total_db_count:,} entri pangan terverifikasi")

        with st.container(border=True):
            st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px;">Catat langsung dari database TKPI (0 kuota AI)</div>', unsafe_allow_html=True)
            db_c1, db_c2, db_c3 = st.columns([2.2, 1.0, 1.3], vertical_alignment="bottom")
            with db_c1:
                pick_idx = st.selectbox(
                    "Pilih pangan",
                    range(len(results)),
                    format_func=lambda idx: f"{results[idx][0]} ({results[idx][2]} kkal/100g)",
                    key="db_pick_idx"
                )
            with db_c2:
                default_pick_w = float(max(5.0, min(1000.0, float(results[pick_idx][10] or 100.0))))
                pick_grams = st.number_input(
                    "Berat (gram)",
                    min_value=5.0,
                    max_value=1000.0,
                    value=default_pick_w,
                    step=5.0,
                    key=f"db_pick_grams_{pick_idx}_{results[pick_idx][0]}",
                )
            with db_c3:
                if st.button("Preview & catat", type="primary", width="stretch", key="btn_db_to_preview"):
                    chosen = results[pick_idx]
                    _open_food_preview({
                        "dish_name": chosen[0],
                        "confidence": "high",
                        "portion_category": f"{pick_grams:.0f}g dari database TKPI",
                        "serving_reference": f"{chosen[9] or '100g'} (~{pick_grams:.0f}g)",
                        "user_caption": f"Database Lab ({pick_grams:.0f}g)",
                        "components": [{
                            "name": chosen[0],
                            "weight_g": float(pick_grams),
                            "energy_kcal_per_100g": float(chosen[2] or 0.0),
                            "protein_g_per_100g": float(chosen[3] or 0.0),
                            "fat_g_per_100g": float(chosen[4] or 0.0),
                            "carb_g_per_100g": float(chosen[5] or 0.0),
                            "fiber_g_per_100g": float(chosen[6] or 0.0),
                            "sodium_mg_per_100g": float(chosen[7] or 0.0),
                            "custom_override": True,
                            "source_label": f"Katalog Resmi ({chosen[1] or 'TKPI'})"
                        }],
                        "health_tip": "Data terverifikasi lab TKPI Kemenkes atau Open Food Facts."
                    }, origin_tab="database")
                    st.rerun()
    else:
        st.info("Tidak ada bahan makanan yang cocok dengan kata kunci tersebut")

    if st.session_state.get("nutrition_data") and st.session_state.get("preview_origin_tab") == "database":
        render_nutrition_preview_card("database", current_user, active_diary_date_str, user_tz, is_admin)

# ================= TAB 4: PANDUAN PENGGUNAAN =================
with tab_guide:
    st.markdown(
        '<div style="padding:8px 0 16px 0;">'
        '<div style="font-size:1.35rem; font-weight:600; color:var(--text-primary);">Panduan penggunaan</div>'
        '<div style="font-size:0.9rem; color:var(--text-secondary); margin-top:4px;">'
        'Ringkasan cara mencatat pola makan, menyesuaikan porsi URT, dan membaca data gizi harian'
        '</div></div>',
        unsafe_allow_html=True,
    )

    col_g1, col_g2 = st.columns([1, 1], gap="large")

    with col_g1:
        with st.container(border=True):
            st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px;">1. Akun pribadi & batas Open Beta</div>', unsafe_allow_html=True)
            st.markdown(
                "- Klik **Masuk / Daftar** di bagian kanan atas untuk membuat akun dengan nama panggilan dan PIN minimal 4 karakter.\n"
                "- Akun terdaftar mendapat kuota 5 scan foto makanan per hari, pelacak berat badan, dan streak harian."
            )

        with st.container(border=True):
            st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px;">2. Fokus klinis, zona waktu & tema</div>', unsafe_allow_html=True)
            st.markdown(
                "- Pilih fokus pemantauan (Diet Sehat, Ibu Hamil, Diabetes, atau Hipertensi) di sidebar agar saran harian menyesuaikan target.\n"
                "- Zona waktu default adalah WITA (UTC+8) dan dapat diubah ke WIB atau WIT kapan saja."
            )

    with col_g2:
        with st.container(border=True):
            st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px;">3. Tiga jalur pencatatan makanan</div>', unsafe_allow_html=True)
            st.markdown(
                "- **Catat Cepat & Menu Cepat:** Ketik langsung di Beranda atau pilih menu harian; semua tampil sebagai Preview sebelum disimpan.\n"
                "- **Foto Piring:** Unggah foto dari tab Catat; wadah bersama atau loyang utuh otomatis ditaksir 1 porsi perorangan.\n"
                "- **Barcode & Database TKPI:** Pindai kode kemasan atau catat langsung dari 1.304 entri lab tanpa kuota AI."
            )

        with st.container(border=True):
            st.markdown('<div style="font-size:0.95rem; font-weight:600; margin-bottom:8px;">4. Edit catatan & Nutri-Grade</div>', unsafe_allow_html=True)
            st.markdown(
                "- Klik tombol edit pada baris Buku Harian untuk mengubah waktu makan atau skala porsi (0.25x sampai 2x) tanpa membuat catatan ganda.\n"
                "- Indeks Nutri-Grade (A sampai D) menandai kepadatan kalori, lemak, natrium, protein, dan serat."
            )

    if is_admin:
        st.markdown("---")
        st.markdown(f'<div class="nc-section-title">Riwayat pembaruan ({APP_CREATOR} · {APP_VERSION})</div>', unsafe_allow_html=True)
        for p in PATCH_NOTES:
            with st.container(border=True):
                st.markdown(f"**{p['version']}** · `{p['date']}`")
                for hl in p["highlights"]:
                    st.markdown(f"- {hl}")

    st.markdown("---")
    st.markdown('<div class="nc-section-title">Pertanyaan umum & ketentuan</div>', unsafe_allow_html=True)
    with st.expander("Dari mana data kalori dan nutrisi ini diambil?"):
        st.write("Data nutrisi berbasis Tabel Komposisi Pangan Indonesia (TKPI) Kementerian Kesehatan RI, USDA FoodData Central, Open Food Facts, dan NilaiGizi.")
    with st.expander("Bagaimana jika hasil estimasi porsi perlu disesuaikan?"):
        st.write("Geser slider ukuran porsi mulai dari 0.25x hingga 2x, lepas centang bahan yang tidak dimakan pada kartu Preview, atau ubah langsung lewat tombol edit di Buku Harian.")
    with st.expander("Disclaimer medis & edukasi gizi"):
        st.write(
            "Nutrisi Cerdas adalah alat bantu edukasi dan pemantauan gizi harian berbasis TKPI Kemenkes RI. "
            "Estimasi porsi foto dapat memiliki selisih bergantung pada pencahayaan dan bahan tersembunyi. "
            "Hasil hitungan maupun saran pada aplikasi ini tidak menggantikan diagnosis, terapi medis, atau konsultasi langsung dengan dokter maupun ahli gizi klinis."
        )
    with st.expander("Kebijakan privasi & keamanan data"):
        st.write(
            "Data akun dilindungi hashing PBKDF2-SHA256 bersalt dan token sesi bertanda tangan HMAC. "
            "Foto makanan hanya dikirim sesaat untuk analisis komponen pangan dan tidak disimpan permanen di server AI. "
            "Anda dapat mengunduh salinan data pribadi (.json) kapan saja melalui menu Cadangan data pribadi di sidebar."
        )

# Footer Tenang & Ringkas
footer_ver_html = f" · <span class='nc-mono'>{APP_VERSION}</span>" if is_admin else " · Open Beta"
st.markdown(
    f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; padding:24px 0 8px 0; margin-top:32px; border-top:1px solid var(--border-col); font-size:0.8125rem; color:var(--text-muted);">'
    f'<span>Nutrisi Cerdas · Basis TKPI Kemenkes RI & Open Food Facts</span>'
    f'<span>{APP_CREATOR} (Muhammad Nabillah){footer_ver_html}</span>'
    f'</div>',
    unsafe_allow_html=True,
)

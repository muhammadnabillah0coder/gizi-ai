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

import sqlite3
import nutrition_engine
import db_history

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
    get_local_now, create_session_token, verify_session_token,
    update_user_preferences, log_weight_entry, get_weight_history, get_logging_streak,
    get_storage_backend_info, get_dashboard_bundle
)
from google_auth import get_google_auth_url, exchange_code_for_user

APP_VERSION = "v4.0.0-beta"
APP_CREATOR = "original by MN"

PATCH_NOTES = [
    {
        "version": "v4.0.0-beta (Terbaru)",
        "date": "18 Nov 2026",
        "highlights": [
            "🛡️ Alur 1-Pintu Anti-Double: Auto-save diam-diam dihapus! Semua jalur catat menampilkan Preview dulu; edit sesi/porsi setelah simpan meng-update catatan yang sama.",
            "🍽️ Smart Porsi Loyang/Wadah Bersama & Pilihan ¼x–2x: Foto kue se-loyang atau buah sebaskom ditaksir per 1 porsi wajar + bisa lepas centang bahan.",
            "✏️ Edit Inline 2-Detik, Pembersih Menu Kembar, Chip 'Sering Kamu Makan', Salin Kemarin, Target Gram Makro, & Persentase Kalori Jujur (>100%).",
            "☁️ Dual-Backend Cloud Database (Supabase PostgreSQL via pg8000 + fallback SQLite) & Pencocokan Bahan Dasar TKPI Gen-2."
        ]
    },
    {
        "version": "v3.0.0-beta",
        "date": "14 Nov 2026",
        "highlights": [
            "🎟️ Mode Open Beta Nyaman: Modul QRIS simulasi ditutup; akun terdaftar mendapat 5x scan foto AI/hari (3x makan berat + 2x jajan) & fitur teks/barcode unlimited.",
            "🔐 Pengamanan Sesi & Akun: Token HMAC URL anti-pembajakan (?u=), hashing PBKDF2 + salt otomatis, dan exact-match Admin.",
            "⚖️ Pelacak Berat Badan, Streak Harian, Mode Fokus Klinis (Diet/Bumil/DM/Hipertensi), & Zona Waktu Indonesia (WITA default).",
            "🧠 Cache Ekstraksi AI Hemat Kuota + Disclaimer Medis & Kebijakan Privasi."
        ]
    },
    {
        "version": "v2.4.0",
        "date": "11 Nov 2026",
        "highlights": [
            "🛡️ Sistem Kurasi & Edit Sebelum Publikasi (Staging Queue) agar data baru tidak mendadak mengubah katalog utama tanpa verifikasi.",
            "🌐 Integrasi Real-Time Open Food Facts API (3+ Juta produk barcode dunia & ritel Indonesia) + Kamera Label Gizi Kemasan.",
            "🚦 Skor Kesehatan Nutri-Grade (A–D) & Rambu Peringatan GGL (Gula, Garam/Natrium, Lemak) standar Kemenkes RI.",
            "🧠 Smart Daily Balancer: Rekomendasi makanan penyeimbang protein & serat otomatis di Dashboard.",
            "🎨 Overhaul 9 Tema Kontras Tinggi 60-30-10 (Bebas masalah teks/kotak hitam ketemu hitam di semua browser)."
        ]
    },
    {
        "version": "v2.2.0",
        "date": "10 Nov 2026",
        "highlights": [
            "⚡ Kotak Catat Cepat (Quick Log Bar) & Bilah Rasio Makronutrien langsung di Dashboard.",
            "🕒 Pengelompokan Buku Harian per Waktu Makan (Sarapan, Makan Siang, Makan Malam, Camilan).",
            "🎯 Kalkulator BMR/TDEE Mifflin-St Jeor otomatis terintegrasi saat pendaftaran akun."
        ]
    }
]

st.set_page_config(
    page_title="Nutrisi Cerdas - Pahami Pola Makanmu Berbasis TKPI Kemenkes",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded"
)


@st.cache_resource(show_spinner=False)
def _ensure_schema_ready():
    init_user_history_tables()
    return True


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_dashboard_bundle_cached(uid: str, target_date_str: str, tz_offset: int, mut_ver: int):
    return get_dashboard_bundle(uid, target_date=target_date_str, tz_offset=tz_offset)


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_pending_foods_cached(mut_ver: int):
    return get_pending_foods(status="pending")


@st.cache_data(ttl=180, show_spinner=False)
def _fetch_custom_foods_cached(uid: str, mut_ver: int):
    return get_custom_foods(uid)


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_tkpi_categories_and_count():
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
    cur = conn.cursor()
    cats = [r[0] for r in cur.execute("SELECT DISTINCT category FROM food_composition WHERE category IS NOT NULL ORDER BY category").fetchall()]
    total_cnt = cur.execute("SELECT COUNT(*) FROM food_composition").fetchone()[0]
    conn.close()
    return cats, total_cnt


@st.cache_data(ttl=180, show_spinner=False)
def _search_tkpi_catalog_cached(query_str: str, sel_cat_str: str):
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
    cur = conn.cursor()
    sql = "SELECT food_name, category, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode FROM food_composition WHERE 1=1"
    params = []
    if query_str:
        sql += " AND (food_name LIKE ? OR barcode LIKE ?)"
        params.append(f"%{query_str}%")
        params.append(f"%{query_str}%")
    if sel_cat_str != "Semua Kategori":
        sql += " AND category = ?"
        params.append(sel_cat_str)
    sql += " ORDER BY food_name ASC LIMIT 50"
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [tuple(r) for r in rows]


def _mark_db_mutated():
    st.session_state["db_mutation_ver"] = st.session_state.get("db_mutation_ver", 0) + 1


_ensure_schema_ready()

# Tangani Redirect Google OAuth Callback (?code=...)
auth_code = st.query_params.get("code", "")
if auth_code:
    redirect_uri = "https://nutrisi-cerdas.streamlit.app"
    user_info, err_details = exchange_code_for_user(auth_code, redirect_uri)
    if not user_info:
        user_info, err_details = exchange_code_for_user(auth_code, "https://nutrisicerdas.streamlit.app")
        if not user_info:
            user_info, err_details = exchange_code_for_user(auth_code, "http://localhost:8501")
        
    if user_info and user_info.get("email"):
        email = user_info["email"]
        name = user_info.get("name") or email.split("@")[0]
        u = get_or_create_user(email, display_name=name, auth_provider="google")
        st.session_state["user"] = u
        st.session_state["nutrition_data"] = None
        _mark_db_mutated()
        st.query_params.clear()
        st.query_params["u"] = u["user_id"]
        st.query_params["s"] = create_session_token(u["user_id"])
        st.query_params["auth"] = "google"
        st.toast(f"Selamat datang, {name}! Akun Google Anda berhasil terhubung.")
        st.rerun()
    else:
        st.error(f"⚠️ Gagal memverifikasi login Google: {err_details}")
        st.caption("Tips: Pastikan Redirect URI di Google Cloud Console persis `https://nutrisi-cerdas.streamlit.app` dan Client ID/Secret sudah ada di Secrets.")

# Inisialisasi Sesi Akun Pengguna dengan Verifikasi Token HMAC (Mencegah Pembajakan ?u=)
saved_user_param = st.query_params.get("u", "")
saved_sig_param = st.query_params.get("s", "")
saved_auth_param = st.query_params.get("auth", "local")

if "user" not in st.session_state:
    if saved_user_param and verify_session_token(saved_user_param, saved_sig_param):
        st.session_state["user"] = get_or_create_user(saved_user_param.strip(), auth_provider=saved_auth_param)
    else:
        if saved_user_param and saved_user_param.strip().lower() != "tamu (demo)":
            st.session_state["auth_url_warning"] = saved_user_param.strip()
            st.query_params.clear()
        st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
else:
    active_uid = st.session_state["user"]["user_id"]
    active_auth = st.session_state["user"].get("auth_provider", "local")
    if active_uid != "Tamu (Demo)":
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
user_theme = current_user.get("theme_preference") or "System Default"
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

# Generator CSS Tema 60-30-10 Anti-Tabrakan Warna (Mengunci Background, Card, Input, Dropdown, Popover, FileUploader, Camera, Alert, & Toast)
def build_theme_css(bg_main: str, bg_sidebar: str, bg_card: str, bg_input: str, text_primary: str, text_muted: str, border_col: str, accent: str, accent_fg: str, tab_bg: str):
    return f"""
        :root {{
            --bg-main: {bg_main};
            --bg-card: {bg_card};
            --bg-input: {bg_input};
            --text-primary: {text_primary};
            --text-muted: {text_muted};
            --border-col: {border_col};
            --accent: {accent};
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
        .apple-ring-card {{
            background: {bg_card} !important;
            color: {text_primary} !important;
            border-radius: 24px;
            padding: 1.5rem;
            border: 1px solid {border_col} !important;
            box-shadow: 0 6px 24px -4px rgba(0, 0, 0, 0.08);
            margin-bottom: 1.2rem;
        }}
        .macro-pill {{
            background: {bg_card} !important;
            color: {text_primary} !important;
            border-radius: 18px;
            padding: 1rem 0.7rem;
            border: 1px solid {border_col} !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
            text-align: center;
        }}
        [data-testid="stVerticalBlockBorderWrapper"], [data-testid="stExpander"] {{
            background-color: {bg_card} !important;
            border-color: {border_col} !important;
            border-radius: 16px !important;
            color: {text_primary} !important;
        }}
        [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p, [data-testid="stExpander"] summary span {{
            color: {text_primary} !important;
        }}
        /* Kunci Kotak Input, Textarea, Number Input, & Selectbox */
        div[data-baseweb="input"], div[data-baseweb="base-input"], div[data-baseweb="textarea"],
        div[data-baseweb="select"] > div {{
            background-color: {bg_input} !important;
            color: {text_primary} !important;
            border-color: {border_col} !important;
            border-radius: 12px !important;
        }}
        div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea,
        div[data-baseweb="select"] span, div[data-baseweb="select"] div {{
            color: {text_primary} !important;
            -webkit-text-fill-color: {text_primary} !important;
        }}
        div[data-baseweb="input"] input::placeholder, div[data-baseweb="textarea"] textarea::placeholder {{
            color: {text_muted} !important;
            -webkit-text-fill-color: {text_muted} !important;
            opacity: 0.8 !important;
        }}
        /* Kunci File Uploader & Dropzone agar tombol Upload tidak putih di atas putih */
        [data-testid="stFileUploader"], [data-testid="stFileUploaderDropzone"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1.5px dashed {accent} !important;
            border-radius: 16px !important;
        }}
        [data-testid="stFileUploaderDropzone"] div,
        [data-testid="stFileUploaderDropzone"] span,
        [data-testid="stFileUploaderDropzone"] small {{
            color: {text_primary} !important;
        }}
        [data-testid="stFileUploaderDropzone"] button {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            border: none !important;
            font-weight: 800 !important;
            border-radius: 10px !important;
        }}
        [data-testid="stFileUploaderDropzone"] button span {{
            color: {accent_fg} !important;
        }}
        /* Kunci Camera Input agar tidak berlatar putih dengan teks putih */
        [data-testid="stCameraInput"], [data-testid="stCameraInput"] > div {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border-radius: 16px !important;
            border: 1px solid {border_col} !important;
        }}
        [data-testid="stCameraInput"] button {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            font-weight: 800 !important;
            border: none !important;
        }}
        [data-testid="stCameraInput"] button span, [data-testid="stCameraInput"] span, [data-testid="stCameraInput"] p {{
            color: {text_primary} !important;
        }}
        [data-testid="stCameraInput"] a {{
            color: {accent} !important;
            font-weight: 700 !important;
        }}
        /* Kunci Kotak Alert (st.info, st.warning, st.success, st.error) & Toast */
        [data-testid="stAlert"], div[role="alert"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1px solid {border_col} !important;
            border-left: 5px solid {accent} !important;
            border-radius: 14px !important;
        }}
        [data-testid="stAlert"] p, [data-testid="stAlert"] span, [data-testid="stAlert"] div {{
            color: {text_primary} !important;
        }}
        [data-testid="stToast"], [data-testid="stToast"] > div {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1.5px solid {accent} !important;
            border-radius: 14px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25) !important;
        }}
        [data-testid="stToast"] p, [data-testid="stToast"] span {{
            color: {text_primary} !important;
        }}
        /* Popover & Dropdown Menu List */
        div[data-baseweb="popover"], div[data-baseweb="popover"] > div,
        [data-testid="stPopoverBody"], ul[role="listbox"], li[role="option"] {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border-color: {border_col} !important;
        }}
        /* Tombol Biasa vs Primary */
        .stButton > button[kind="secondary"], [data-testid="stPopover"] > div > button {{
            background-color: {bg_card} !important;
            color: {text_primary} !important;
            border: 1.5px solid {border_col} !important;
        }}
        .stButton > button[kind="secondary"] p, .stButton > button[kind="secondary"] span,
        [data-testid="stPopover"] > div > button p, [data-testid="stPopover"] > div > button span {{
            color: {text_primary} !important;
        }}
        .stButton > button[kind="primary"] {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            border: none !important;
        }}
        .stButton > button[kind="primary"] p, .stButton > button[kind="primary"] span {{
            color: {accent_fg} !important;
        }}
        .ring-title, .macro-lbl {{
            font-size: 0.78rem;
            font-weight: 700;
            color: {text_muted} !important;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }}
        .ring-val {{ font-size: 2.1rem; font-weight: 800; color: {text_primary} !important; margin: 0.25rem 0; }}
        .macro-num {{ font-size: 1.45rem; font-weight: 800; margin: 0.15rem 0; }}
        /* Tab Navigasi Kompak agar Muat 1 Layar HP Tanpa Scroll Samping */
        div[data-baseweb="tab-list"] {{
            gap: 6px;
            background-color: {tab_bg} !important;
            padding: 5px;
            border-radius: 16px;
            margin-bottom: 1.1rem;
            border: 1px solid {border_col};
            flex-wrap: wrap !important;
        }}
        button[data-baseweb="tab"] {{
            border-radius: 12px !important;
            font-size: 0.88rem !important;
            font-weight: 700 !important;
            padding: 0.5rem 0.85rem !important;
            color: {text_muted} !important;
            background-color: transparent !important;
            flex: 1 1 auto !important;
            justify-content: center !important;
        }}
        button[data-baseweb="tab"] p, button[data-baseweb="tab"] span {{
            color: {text_muted} !important;
            font-weight: 700 !important;
            font-size: 0.88rem !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] {{
            background-color: {accent} !important;
            color: {accent_fg} !important;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.15) !important;
        }}
        button[data-baseweb="tab"][aria-selected="true"] p,
        button[data-baseweb="tab"][aria-selected="true"] span {{
            color: {accent_fg} !important;
        }}
    """

# 9 Pilihan Tema Proporsi 60-30-10 Kontras Tinggi
THEME_STYLES = {
    "System Default": """
        :root { --text-muted: #64748b; }
        .apple-ring-card {
            background: rgba(125, 125, 125, 0.08);
            border: 1px solid rgba(125, 125, 125, 0.2);
            border-radius: 24px;
            padding: 1.8rem;
            margin-bottom: 1.5rem;
        }
        .macro-pill {
            background: rgba(125, 125, 125, 0.08);
            border-radius: 20px;
            padding: 1.2rem 1rem;
            border: 1px solid rgba(125, 125, 125, 0.2);
            text-align: center;
        }
        .ring-title, .macro-lbl { color: inherit; opacity: 0.75; font-weight: 700; text-transform: uppercase; font-size: 0.8rem; }
        .ring-val, .macro-num { font-weight: 800; }
        div[data-baseweb="tab-list"] {
            gap: 10px;
            background-color: rgba(125, 125, 125, 0.15);
            padding: 6px;
            border-radius: 18px;
            margin-bottom: 1.5rem;
        }
        button[data-baseweb="tab"] {
            border-radius: 14px !important;
            font-size: 1.0rem !important;
            font-weight: 700 !important;
            padding: 0.65rem 1.35rem !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #10b981 !important;
            color: #ffffff !important;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25) !important;
        }
    """,
    "Apple Light": build_theme_css(
        bg_main="#F8FAFC", bg_sidebar="#F1F5F9", bg_card="#FFFFFF", bg_input="#F8FAFC",
        text_primary="#0F172A", text_muted="#475569", border_col="#CBD5E1",
        accent="#10B981", accent_fg="#FFFFFF", tab_bg="#E2E8F0"
    ),
    "Cal AI Dark": build_theme_css(
        bg_main="#0B0F17", bg_sidebar="#111827", bg_card="#161F30", bg_input="#1E293B",
        text_primary="#F8FAFC", text_muted="#94A3B8", border_col="#2D3B55",
        accent="#00F5A0", accent_fg="#090D16", tab_bg="#131B2E"
    ),
    "Mint Fresh": build_theme_css(
        bg_main="#F0FDF4", bg_sidebar="#DCFCE7", bg_card="#FFFFFF", bg_input="#F0FDF4",
        text_primary="#064E3B", text_muted="#047857", border_col="#A7F3D0",
        accent="#059669", accent_fg="#FFFFFF", tab_bg="#D1FAE5"
    ),
    "Warm Sunset": build_theme_css(
        bg_main="#FFFBEB", bg_sidebar="#FEF3C7", bg_card="#FFFFFF", bg_input="#FFFBEB",
        text_primary="#292524", text_muted="#78716C", border_col="#FDE68A",
        accent="#D97706", accent_fg="#FFFFFF", tab_bg="#FEF3C7"
    ),
    "Ocean Breeze": build_theme_css(
        bg_main="#F0F9FF", bg_sidebar="#E0F2FE", bg_card="#FFFFFF", bg_input="#F0F9FF",
        text_primary="#0C4A6E", text_muted="#0369A1", border_col="#BAE6FD",
        accent="#0284C7", accent_fg="#FFFFFF", tab_bg="#E0F2FE"
    ),
    "Royal Purple Dark": build_theme_css(
        bg_main="#0F0A1C", bg_sidebar="#160F29", bg_card="#1E1436", bg_input="#2A1C4B",
        text_primary="#F5F3FF", text_muted="#C4B5FD", border_col="#3B2766",
        accent="#A855F7", accent_fg="#FFFFFF", tab_bg="#18102C"
    ),
    "Sakura Rose": build_theme_css(
        bg_main="#FFF1F2", bg_sidebar="#FFE4E6", bg_card="#FFFFFF", bg_input="#FFF1F2",
        text_primary="#4C0519", text_muted="#9F1239", border_col="#FECDD3",
        accent="#E11D48", accent_fg="#FFFFFF", tab_bg="#FFE4E6"
    ),
    "Cyberpunk Gold": build_theme_css(
        bg_main="#09090B", bg_sidebar="#121216", bg_card="#18181B", bg_input="#27272A",
        text_primary="#FAFAFA", text_muted="#A1A1AA", border_col="#3F3F46",
        accent="#EAB308", accent_fg="#09090B", tab_bg="#18181B"
    ),
}

# Terapkan CSS Dinamis Sesuai Preferensi
st.markdown(f"""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] {{
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }}
    .apple-tip {{
        background: rgba(16, 185, 129, 0.12);
        border: 1px solid rgba(16, 185, 129, 0.3);
        border-left: 5px solid #10b981;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        font-size: 0.93rem;
        line-height: 1.5;
        margin: 1.2rem 0;
    }}
    .stButton>button {{
        border-radius: 14px;
        font-weight: 700;
        padding: 0.6rem 1.4rem;
    }}
    {THEME_STYLES.get(user_theme, THEME_STYLES["System Default"])}
</style>
""", unsafe_allow_html=True)

# Konstanta pilihan porsi & waktu makan (scan_status sudah dihitung 1x di dash_bundle)

TZ_OPTIONS = {
    7: "WIB (UTC+7 — Jawa/Sumatra/Kalbar)",
    8: "WITA (UTC+8 — Tanah Grogot/Kaltim/Bali)",
    9: "WIT (UTC+9 — Papua/Maluku)"
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
    0.25: "¼ Porsi / 1 Potong Kecil (0.25x)",
    0.5: "½ Porsi (0.5x)",
    0.75: "¾ Porsi (0.75x)",
    1.0: "1 Porsi Standar (1.0x)",
    1.5: "1.5x Porsi",
    2.0: "2x Porsi",
}
MEAL_SESSION_MAP = {
    "🌅 Sarapan": "Sarapan",
    "☀️ Makan Siang": "Makan Siang",
    "🌙 Makan Malam": "Makan Malam",
    "🍪 Camilan": "Camilan",
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
    """Menyusun laporan WhatsApp rapi per waktu makan dengan persentase jujur (>100% tidak terpotong)."""
    meal_icons = {
        "Sarapan": "🌅 Sarapan",
        "Makan Siang": "☀️ Makan Siang",
        "Makan Malam": "🌙 Makan Malam",
        "Camilan": "🍪 Camilan",
    }
    grouped = {}
    for m in today_meals:
        mt = _normalize_meal_key(m.get("meal_type"))
        grouped.setdefault(mt, []).append(m)

    lines = [
        f"🥗 *Laporan Nutrisi Harian Saya ({diary_date.strftime('%d %B %Y')})*",
        f"👤 Akun: {display_name}",
        f"🔥 *Total Kalori:* {today_kcal:,.1f} / {target_kcal:,.0f} kkal ({pct_actual}%)",
        f"🥩 P: {today_totals['protein_g']}g | 🥑 L: {today_totals['fat_g']}g | 🍚 K: {today_totals['carb_g']}g | 🥦 S: {today_totals['fiber_g']}g",
        "",
        "📋 *Menu Hari Ini:*",
    ]
    idx_num = 1
    for mt in ["Sarapan", "Makan Siang", "Makan Malam", "Camilan", "Lainnya"]:
        if mt not in grouped:
            continue
        lines.append(f"*{meal_icons.get(mt, mt)}*")
        for m in grouped[mt]:
            lines.append(f"{idx_num}. {m['dish_name']} ({m['energy_kcal']} kkal)")
            idx_num += 1

    lines.append("\nCek & hitung nutrisi makananmu di: https://nutrisi-cerdas.streamlit.app")
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
            st.markdown(f"""<div style="background: rgba(16, 185, 129, 0.14); border: 1.5px solid #10b981; border-radius: 14px; padding: 0.7rem 1rem; margin-bottom: 0.7rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;"><span style="font-weight: 800; color: #10b981;">🟢 SUDAH TERSIMPAN di Sesi {saved_mt}</span><span style="font-size: 0.82rem; opacity: 0.88;">Mengubah porsi/sesi di bawah akan memperbarui catatan ini (tidak mendobel).</span></div>""", unsafe_allow_html=True)
        else:
            st.markdown("""<div style="background: rgba(245, 158, 11, 0.14); border: 1.5px solid #f59e0b; border-radius: 14px; padding: 0.7rem 1rem; margin-bottom: 0.7rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;"><span style="font-weight: 800; color: #d97706;">🟡 PREVIEW — BELUM DISIMPAN</span><span style="font-size: 0.82rem; opacity: 0.88;">Atur ukuran porsi & pilih waktu makan, lalu klik <strong>Simpan ke Buku Harian</strong>.</span></div>""", unsafe_allow_html=True)

        st.markdown(f"### 🍽️ **{data.get('dish_name', 'Menu Makanan')}**")
        serving_ref = (data.get("serving_reference") or "").strip()
        if data.get("is_shared_platter"):
            ref_txt = serving_ref or "1 potong / 1 porsi makan perorangan"
            st.info(f"🍰 **Porsi Perorangan Terdeteksi:** Foto terlihat menampilkan loyang/wadah bersama. Nilai `1.0x` ditaksir untuk **{ref_txt}** (bukan seisi loyang). Sesuaikan ke `¼x–2x` bila perlu.")
        elif serving_ref:
            st.caption(f"📏 Patokan 1.0x: **{serving_ref}**")

        all_components = data.get("components", [])
        active_components = all_components
        if len(all_components) > 1:
            with st.expander(f"🧩 **Pilih Komponen Piring ({len(all_components)} bahan — lepas centang yang tidak dimakan)**", expanded=False):
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
            st.warning("⚠️ Pilih minimal 1 komponen bahan untuk menghitung kalori.")
            if st.button("❌ Tutup Preview", key=f"prev_close_empty_{context_key}_{nonce}"):
                st.session_state["nutrition_data"] = None
                st.rerun()
            return

        st.markdown("##### ⚖️ Sesuaikan Ukuran Porsi:")
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
        badges_html = " ".join([
            f'<span style="background: rgba(125,125,125,0.12); color: {b_col}; border: 1px solid {b_col}; font-size: 0.75rem; font-weight: 800; padding: 0.2rem 0.6rem; border-radius: 999px;">{b_txt}</span>'
            for b_txt, b_col in ng["badges"]
        ])
        st.markdown(f"""<div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; background: rgba(125, 125, 125, 0.06); border: 1px solid rgba(125, 125, 125, 0.16); border-radius: 16px; padding: 0.85rem 1.2rem; margin: 0.6rem 0;"><div style="display: flex; align-items: center; gap: 12px;"><div style="background: {ng['color']}; color: #ffffff; font-size: 1.4rem; font-weight: 900; width: 44px; height: 44px; border-radius: 12px; display: flex; align-items: center; justify-content: center;">{ng['grade']}</div><div><div style="font-size: 0.75rem; font-weight: 800; opacity: 0.75; text-transform: uppercase;">Indeks Nutri-Grade & GGL</div><div style="font-size: 1.0rem; font-weight: 800;">{ng['label']}</div></div></div><div style="display: flex; gap: 6px; flex-wrap: wrap;">{badges_html}</div></div>""", unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='macro-pill'><div class='macro-num'>{t_tot['energy_kcal']}</div><div class='macro-lbl'>Kalori (kkal)</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#0284c7;'>{t_tot['protein_g']}g</div><div class='macro-lbl'>Protein</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#d97706;'>{t_tot['fat_g']}g</div><div class='macro-lbl'>Lemak</div></div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#059669;'>{t_tot['carb_g']}g</div><div class='macro-lbl'>Karbohidrat</div></div>", unsafe_allow_html=True)

        meal_keys = list(MEAL_SESSION_MAP.keys())
        meal_vals = list(MEAL_SESSION_MAP.values())
        target_mt = saved_mt or _infer_meal_type(tz_offset)
        def_idx = meal_vals.index(target_mt) if target_mt in meal_vals else 1

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
        sel_meal_label = st.radio(
            "Waktu Makan:",
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
                if st.button(f"💾 Simpan ke Buku Harian ({active_user['display_name']})", type="primary", use_container_width=True, key=f"prev_btn_save_{context_key}_{nonce}"):
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
                    st.toast(f"✅ {data.get('dish_name')} tersimpan ke {sel_meal_clean}!")
                    st.rerun()
            with col_act2:
                if st.button("❌ Tutup", use_container_width=True, key=f"prev_btn_clear_{context_key}_{nonce}"):
                    st.session_state["nutrition_data"] = None
                    st.rerun()
        else:
            col_u1, col_u2, col_u3 = st.columns([2.2, 1.3, 1.3])
            with col_u1:
                if st.button(f"🔄 Perbarui Catatan Ini ({sel_meal_clean})", type="primary", use_container_width=True, key=f"prev_btn_upd_{context_key}_{nonce}"):
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
                    st.toast(f"🔄 Catatan diperbarui ke {sel_meal_clean} ({t_tot['energy_kcal']} kkal)!")
                    st.rerun()
            with col_u2:
                if st.button("↩️ Batalkan Simpan", use_container_width=True, key=f"prev_btn_undo_{context_key}_{nonce}"):
                    delete_meal_log(saved_id, active_user["user_id"])
                    st.session_state["nutrition_data"].pop("saved_log_id", None)
                    st.session_state["nutrition_data"].pop("saved_meal_type", None)
                    if st.session_state.get("last_saved_item") and st.session_state["last_saved_item"].get("id") == saved_id:
                        st.session_state["last_saved_item"] = None
                    _mark_db_mutated()
                    st.toast("↩️ Simpanan dibatalkan. Kini kembali ke mode Preview.")
                    st.rerun()
            with col_u3:
                if st.button("➕ Menu Baru", use_container_width=True, key=f"prev_btn_new_{context_key}_{nonce}"):
                    st.session_state["nutrition_data"] = None
                    st.rerun()

        if data.get("health_tip"):
            st.markdown(f"""<div class="apple-tip">💡 <strong>Saran Nutrisi:</strong> {data['health_tip']}</div>""", unsafe_allow_html=True)

        with st.expander("🔍 **Lihat Rincian Komposisi Lab & Koreksi Angka Gizi**", expanded=False):
            table_rows = [{
                "Bahan": it["input_name"],
                "Referensi Lab": it["tkpi_matched_name"],
                "Berat": f"{it['weight_g']} g",
                "Kalori": f"{it['energy_kcal']} kkal",
                "Protein": f"{it['protein_g']} g",
                "Lemak": f"{it['fat_g']} g",
                "Karbo": f"{it['carb_g']} g"
            } for it in calc_res["items"]]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

            st.markdown("##### ✏️ **Koreksi / Edit Nilai Gizi**")
            ed_c1, ed_c2 = st.columns(2)
            with ed_c1:
                ed_name = st.text_input("Nama Pangan / Produk:", value=data.get("dish_name", "Menu Makanan"), key=f"ed_res_name_{context_key}_{nonce}")
                ed_cat = st.text_input("Kategori Pangan:", value="Produk Terverifikasi MN", key=f"ed_res_cat_{context_key}_{nonce}")
                ed_bc = st.text_input("Nomor Barcode (Opsional):", value=str(data.get("barcode") or ""), key=f"ed_res_bc_{context_key}_{nonce}")
                ed_serv = st.text_input("Satuan Saji:", value=str(data.get("serving_unit") or "1 porsi"), key=f"ed_res_serv_{context_key}_{nonce}")
            with ed_c2:
                ed_kcal = st.number_input("Kalori (kkal):", min_value=0.0, value=float(t_tot["energy_kcal"]), step=5.0, key=f"ed_res_kcal_{context_key}_{nonce}")
                ed_p = st.number_input("Protein (g):", min_value=0.0, value=float(t_tot["protein_g"]), step=0.5, key=f"ed_res_p_{context_key}_{nonce}")
                ed_f = st.number_input("Lemak (g):", min_value=0.0, value=float(t_tot["fat_g"]), step=0.5, key=f"ed_res_f_{context_key}_{nonce}")
                ed_c = st.number_input("Karbohidrat (g):", min_value=0.0, value=float(t_tot["carb_g"]), step=0.5, key=f"ed_res_c_{context_key}_{nonce}")

            col_pub1, col_pub2 = st.columns(2)
            with col_pub1:
                if st.button("✅ Terapkan Koreksi ke Hasil Ini", use_container_width=True, key=f"btn_apply_edit_local_{context_key}_{nonce}"):
                    # Bagi proporsional agar saat p_mult = 1.0x nilai akhir sama persis dengan ed_kcal
                    inv_mult = 1.0 / max(p_mult, 0.1)
                    st.session_state["nutrition_data"]["dish_name"] = ed_name
                    st.session_state["nutrition_data"]["components"] = [{
                        "name": ed_name,
                        "weight_g": round(100.0 * inv_mult, 2),
                        "energy_kcal_per_100g": ed_kcal,
                        "protein_g_per_100g": ed_p,
                        "fat_g_per_100g": ed_f,
                        "carb_g_per_100g": ed_c,
                        "fiber_g_per_100g": float(t_tot.get("fiber_g", 0.0)),
                        "sodium_mg_per_100g": float(t_tot.get("sodium_mg", 0.0)),
                        "custom_override": True,
                        "source_label": f"Koreksi Pengguna ({ed_name})"
                    }]
                    if saved_id:
                        new_tot = {
                            "energy_kcal": ed_kcal, "protein_g": ed_p, "fat_g": ed_f,
                            "carb_g": ed_c, "fiber_g": float(t_tot.get("fiber_g", 0.0)),
                            "sodium_mg": float(t_tot.get("sodium_mg", 0.0)),
                        }
                        res_upd = update_meal_log(saved_id, active_user["user_id"], dish_name=ed_name, totals=new_tot, multiplier=p_mult, meal_type=sel_meal_clean)
                        if res_upd:
                            st.session_state["last_saved_item"] = res_upd
                        _mark_db_mutated()
                    st.toast("Nilai gizi pada kartu hasil berhasil diperbarui!")
                    st.rerun()
            with col_pub2:
                if is_adm:
                    if st.button("🚀 Publikasikan Resmi ke Katalog Utama (Admin)", type="primary", use_container_width=True, key=f"btn_pub_catalog_now_{context_key}_{nonce}"):
                        publish_food_to_catalog(
                            food_name=ed_name, category=ed_cat,
                            kcal_100=ed_kcal, p_100=ed_p, f_100=ed_f, c_100=ed_c,
                            fib_100=float(t_tot.get("fiber_g", 0.0)),
                            barcode=ed_bc, serving_unit=ed_serv, serving_weight=100.0
                        )
                        _fetch_tkpi_categories_and_count.clear()
                        _search_tkpi_catalog_cached.clear()
                        _mark_db_mutated()
                        st.success(f"🎉 '{ed_name}' berhasil dipublikasikan secara resmi ke katalog utama!")
                else:
                    if st.button("📥 Ajukan ke Antrean Kurasi Admin", type="primary", use_container_width=True, key=f"btn_stage_catalog_now_{context_key}_{nonce}"):
                        stage_pending_food(
                            food_name=ed_name, category=ed_cat,
                            kcal_100=ed_kcal, p_100=ed_p, f_100=ed_f, c_100=ed_c,
                            fib_100=float(t_tot.get("fiber_g", 0.0)),
                            barcode=ed_bc, serving_unit=ed_serv, serving_weight=100.0,
                            source_origin="Koreksi Pengguna", submitted_by=active_user["user_id"]
                        )
                        _mark_db_mutated()
                        st.success("✅ Berhasil diajukan ke antrean kurasi Admin sebelum dipublikasikan!")

# Sidebar: Akun Pribadi & Target Harian (Efisien, Bersih, & Kompak)
with st.sidebar:
    # 1. Branding Header Ramping + Badge original by MN (Versi teknis hanya untuk Admin)
    ver_badge_sb = f'<span style="background: rgba(59, 130, 246, 0.15); color: #3b82f6; font-size: 0.65rem; font-weight: 800; padding: 0.1rem 0.45rem; border-radius: 999px;">{APP_VERSION}</span>' if is_admin else ''
    st.markdown(f"""<div style="display: flex; align-items: center; gap: 10px; margin-bottom: 0.8rem; padding-bottom: 0.6rem; border-bottom: 1px solid rgba(125, 125, 125, 0.15);">
<span style="font-size: 1.9rem;">🥗</span>
<div>
<div style="font-weight: 800; font-size: 1.15rem; line-height: 1.15;">Nutrisi Cerdas</div>
<div style="font-size: 0.7rem; color: #10b981; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em;">TKPI Kemenkes + Open Food Facts</div>
<div style="margin-top: 4px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap;"><span style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.65rem; font-weight: 800; padding: 0.1rem 0.45rem; border-radius: 999px; border: 1px solid rgba(16, 185, 129, 0.3);">{APP_CREATOR}</span>{ver_badge_sb}</div>
</div>
</div>""", unsafe_allow_html=True)
    
    # 2. Status Akun Ringkas
    if current_user["user_id"] == "Tamu (Demo)":
        st.markdown("""
        <div style="background: rgba(245, 158, 11, 0.12); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 14px; padding: 0.75rem 0.9rem; margin-bottom: 0.8rem;">
            <div style="font-size: 0.76rem; font-weight: 800; color: #d97706; text-transform: uppercase;">🌱 Status: Mode Demo</div>
            <div style="font-size: 0.83rem; margin-top: 0.25rem; line-height: 1.35;">
                Buat akun gratis dalam 15 detik agar catatan makan, grafik berat badan, & 5x scan foto AI/hari terkunci atas namamu.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        if is_admin:
            badge_html = '<span style="background: rgba(245, 158, 11, 0.2); color: #d97706; font-size: 0.72rem; font-weight: 800; padding: 0.18rem 0.55rem; border-radius: 999px;">👑 FOUNDER / ADMIN</span>'
        else:
            badge_html = f'<span style="background: rgba(16, 185, 129, 0.2); color: #059669; font-size: 0.72rem; font-weight: 800; padding: 0.18rem 0.55rem; border-radius: 999px;">🎟️ Open Beta ({scan_status["scans_today"]}/{scan_status["max_scans"]} Scan Foto)</span>'

        st.markdown(f"""
        <div style="background: rgba(125, 125, 125, 0.08); border: 1px solid rgba(125, 125, 125, 0.16); border-radius: 14px; padding: 0.75rem 0.9rem; margin-bottom: 0.5rem;">
            <div style="font-weight: 700; font-size: 0.92rem;">👤 {current_user['display_name']}</div>
            <div style="margin-top: 0.35rem;">{badge_html}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("🚪 Keluar Akun (Logout)", use_container_width=True, key="sb_btn_logout"):
            st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
            st.session_state["nutrition_data"] = None
            st.query_params.clear()
            _mark_db_mutated()
            st.toast("Anda telah berhasil keluar dari akun.")
            st.rerun()

    # 3. Target Kalori Harian (Cepat & Praktis)
    st.markdown("##### 🎯 **Target Kalori Harian**")
    current_target = float(current_user.get("daily_calorie_target") or 2000.0)
    new_target = st.number_input("Target Kalori (kkal/hari):", min_value=1000, max_value=4000, value=int(current_target), step=50, key="sb_target_kcal")
    if new_target != current_target:
        update_calorie_target(current_user["user_id"], float(new_target))
        st.session_state["user"]["daily_calorie_target"] = float(new_target)
        _mark_db_mutated()
        st.toast("Target kalori diperbarui!")
        st.rerun()

    # Expander Tersembunyi untuk Kalibrasi Ulang Target BMR/TDEE
    with st.expander("🧮 Hitung Ulang Target Ideal (BMR)", expanded=False):
        st.caption("Hitung target kalori berdasarkan rumus standar Mifflin-St Jeor / Kemenkes RI:")
        gender = st.radio("Jenis Kelamin:", ["Pria", "Wanita"], horizontal=True, key="sb_bmr_gen")
        bb = st.number_input("Berat Badan (kg):", value=float(current_user.get("weight_kg") or 65.0), step=1.0, key="sb_bmr_bb")
        tb = st.number_input("Tinggi Badan (cm):", value=float(current_user.get("height_cm") or 170.0), step=1.0, key="sb_bmr_tb")
        usia = st.number_input("Usia (tahun):", value=int(current_user.get("age_years") or 25), step=1, key="sb_bmr_age")
        aktivitas = st.selectbox("Aktivitas Harian:", [
            "Sedentari (Jarang olahraga / di depan laptop)",
            "Ringan (Olahraga 1-3 hari/minggu)",
            "Sedang (Olahraga 3-5 hari/minggu)",
            "Sangat Aktif (Latihan intensif setiap hari)"
        ], key="sb_bmr_act")
        tujuan = st.selectbox("Tujuan Program:", [
            "Turunkan Berat Badan (Defisit 400 kkal)",
            "Jaga Berat Badan Ideal (Maintenance)",
            "Tambah Berat / Massa Otot (Surplus 400 kkal)"
        ], key="sb_bmr_goal")
        
        if st.button("Terapkan Target Kalori", use_container_width=True, key="sb_btn_apply_bmr"):
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
            st.success(f"🎯 Target kalori berhasil diatur menjadi **{recom_target} kkal/hari**!")
            st.rerun()

    # 3b. Preferensi Fokus Kesehatan & Zona Waktu (Default WITA UTC+8)
    with st.expander("🩺 Fokus Kesehatan & Zona Waktu", expanded=False):
        focus_idx = FOCUS_GOALS.index(user_focus) if user_focus in FOCUS_GOALS else 0
        sel_focus = st.selectbox("Fokus Pemantauan Gizi:", FOCUS_GOALS, index=focus_idx, key="sb_focus_goal")
        tz_keys = list(TZ_OPTIONS.keys())
        tz_idx = tz_keys.index(user_tz) if user_tz in tz_keys else 1
        sel_tz = st.selectbox("Zona Waktu:", tz_keys, index=tz_idx, format_func=lambda k: TZ_OPTIONS[k], key="sb_tz_select")
        if sel_focus != user_focus or sel_tz != user_tz:
            update_user_preferences(current_user["user_id"], timezone_offset=sel_tz, focus_goal=sel_focus)
            st.session_state["user"]["timezone_offset"] = sel_tz
            st.session_state["user"]["focus_goal"] = sel_focus
            st.session_state["selected_diary_date"] = get_local_now(sel_tz).date()
            _mark_db_mutated()
            st.toast("Preferensi fokus & zona waktu disimpan!")
            st.rerun()

    # 4. Pengaturan Tema Tampilan (9 Tema Proporsi 60-30-10 Kontras Tinggi)
    st.markdown("---")
    with st.expander("🎨 Pilihan Tema Tampilan (9 Tema)", expanded=False):
        theme_options = list(THEME_STYLES.keys())
        current_idx = theme_options.index(user_theme) if user_theme in theme_options else 0
        selected_theme = st.selectbox("Pilih Tema Warna UI:", theme_options, index=current_idx, key="sb_theme_picker")
        if selected_theme != user_theme:
            update_user_theme(current_user["user_id"], selected_theme)
            st.session_state["user"]["theme_preference"] = selected_theme
            _mark_db_mutated()
            st.toast(f"Tema diubah ke {selected_theme}!")
            st.rerun()

    # 4b. Jaring Pengaman Cadangan Data Ringkas (Khusus Akun Terdaftar, Tersembunyi Rapi)
    if current_user["user_id"] != "Tamu (Demo)":
        with st.expander("📦 Cadangan Data Pribadi (Opsional)", expanded=False):
            st.caption("Unduh salinan riwayat makan & berat badan Anda kapan saja:")
            if st.button("📦 Siapkan File Cadangan (.json)", use_container_width=True, key="sb_btn_prep_json"):
                st.session_state["prepared_backup_json"] = export_user_data_json(current_user["user_id"])
            if st.session_state.get("prepared_backup_json"):
                st.download_button(
                    "⬇️ Unduh Salinan Diary (.json)",
                    data=st.session_state["prepared_backup_json"],
                    file_name=f"nutrisi_cerdas_{current_user['user_id']}_{get_local_now(user_tz).strftime('%Y%m%d')}.json",
                    mime="application/json",
                    use_container_width=True,
                    key="sb_btn_export_json"
                )
            up_bk = st.file_uploader("Pulihkan dari file .json:", type=["json"], key="sb_up_restore_json")
            if up_bk and st.button("♻️ Pulihkan Sekarang", use_container_width=True, key="sb_btn_do_restore"):
                ok_imp, msg_imp = import_user_data_json(current_user["user_id"], up_bk.getvalue().decode("utf-8"))
                if ok_imp:
                    _mark_db_mutated()
                    st.success(msg_imp)
                    st.rerun()
                else:
                    st.error(msg_imp)

    # 5. Informasi Versi Web Patch Update & Status Cloud Database (Hanya Tampil untuk Admin)
    if is_admin:
        backend_info = get_storage_backend_info()
        with st.expander("☁️ Status Cloud Database (Admin Only)", expanded=False):
            if backend_info["mode"] == "supabase":
                st.success(f"🟢 **{backend_info['label']}**\nHost: `{backend_info['host']}`")
            else:
                st.warning(f"🟡 **{backend_info['label']}**")
                if backend_info.get("error"):
                    st.caption(f"Detail: `{backend_info['error'][:120]}`")
                st.caption(
                    "Agar akun & diary tersimpan permanen lintas restart Streamlit Cloud:\n"
                    "1. Buat proyek gratis di **supabase.com** (Region Singapore).\n"
                    "2. Klik **Connect → Session Pooler** lalu salin URI PostgreSQL.\n"
                    "3. Tempel `DATABASE_URL = \"...\"` di **Streamlit Cloud → Settings → Secrets**."
                )

        with st.expander(f"📋 Web Patch Update ({APP_VERSION} - Admin Only)", expanded=False):
            st.caption(f"Dikembangkan oleh **Muhammad Nabillah ({APP_CREATOR})**")
            for p in PATCH_NOTES:
                st.markdown(f"**🚀 {p['version']}** _{p['date']}_")
                for hl in p["highlights"]:
                    st.caption(f"• {hl}")
                st.markdown("---")

# Header Brand Utama dengan Logo Menonjol & Kotak Login Akun Langsung di Halaman Utama

if st.session_state.get("auth_url_warning"):
    st.warning(
        f"🔒 Untuk menjaga privasi buku harian **{st.session_state['auth_url_warning']}**, "
        "tautan akun lama memerlukan verifikasi PIN terlebih dahulu. Silakan klik **🔑 Masuk / Daftar**."
    )
    st.session_state.pop("auth_url_warning", None)

col_head1, col_head2 = st.columns([2, 1.2], vertical_alignment="center")

with col_head1:
    import base64
    logo_base64 = ""
    logo_path = os.path.join(os.path.dirname(__file__), "logo_nutrisi_cerdas_512.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode()
            
    logo_img_html = f'<img src="data:image/png;base64,{logo_base64}" style="width: 82px; height: 82px; border-radius: 24px; box-shadow: 0 10px 25px -4px rgba(16, 185, 129, 0.4);" />' if logo_base64 else '<div style="font-size: 3.5rem; background: linear-gradient(135deg, #10b981 0%, #059669 100%); width: 82px; height: 82px; display: flex; align-items: center; justify-content: center; border-radius: 24px; box-shadow: 0 10px 25px -4px rgba(16, 185, 129, 0.4);">🥗</div>'
    creator_badge_text = f"✨ {APP_CREATOR} • {APP_VERSION}" if is_admin else "🧪 Open Beta Gratis"

    st.markdown(f"""
    <div style="display: flex; align-items: center; gap: 18px; margin-bottom: 0.5rem; padding: 0.5rem 0;">
        {logo_img_html}
        <div>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <h1 style="font-size: 2.5rem; font-weight: 800; margin: 0; letter-spacing: -0.02em;">Nutrisi Cerdas</h1>
                <span style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.76rem; font-weight: 800; padding: 0.3rem 0.75rem; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid rgba(16, 185, 129, 0.3);">
                    TKPI KEMENKES + OPEN FOOD FACTS • AI VISION
                </span>
                <span style="background: linear-gradient(135deg, #8b5cf6 0%, #6d28d9 100%); color: #ffffff; font-size: 0.72rem; font-weight: 800; padding: 0.28rem 0.7rem; border-radius: 9999px; letter-spacing: 0.04em; box-shadow: 0 2px 10px rgba(139, 92, 246, 0.3);">
                    {creator_badge_text}
                </span>
            </div>
            <p style="margin: 0.25rem 0 0 0; opacity: 0.82; font-size: 1.02rem; font-weight: 500;">
                Kalkulator & Diary Nutrisi: Pahami Pola Makanmu Berbasis Rujukan Pangan Terverifikasi
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_head2:
    with st.container(border=True):
        if is_admin:
            tier_badge = "👑 ADMIN (Unlimited)"
        elif current_user["user_id"] == "Tamu (Demo)":
            tier_badge = f"🌱 Mode Demo ({scan_status['scans_today']}/{scan_status['max_scans']} Scan Foto)"
        else:
            tier_badge = f"🎟️ Open Beta ({scan_status['scans_today']}/{scan_status['max_scans']} Scan Foto)"
            
        st.markdown(f"👤 **{current_user['display_name']}** • `{tier_badge}`")
        
        c_acc1, c_acc2 = st.columns([1, 1])
        with c_acc1:
            if current_user["user_id"] == "Tamu (Demo)":
                btn_acc_label = "🔑 Masuk / Daftar"
            else:
                btn_acc_label = f"⚙️ Akun: {current_user['display_name'].split()[0]}"

            with st.popover(btn_acc_label, use_container_width=True):
                if current_user["user_id"] != "Tamu (Demo)":
                    st.markdown(f"##### 👤 Akun: **{current_user['display_name']}**")
                    st.caption(f"ID: `{current_user['user_id']}` • Fokus: `{user_focus}`")
                    st.markdown("---")
                    if st.button("🚪 Keluar dari Akun (Logout)", type="primary", use_container_width=True, key="btn_logout_top"):
                        st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
                        st.session_state["nutrition_data"] = None
                        st.query_params.clear()
                        _mark_db_mutated()
                        st.toast("Anda telah berhasil keluar dari akun.")
                        st.rerun()
                    st.markdown("---")
                    st.caption("Ingin berganti akun lain?")

                sub_login, sub_reg = st.tabs(["🔐 Masuk Akun", "📝 Buat Akun Baru"])
                
                with sub_login:
                    st.markdown("##### 🔐 Masuk ke Diary Anda")
                    in_uid = st.text_input("Email / ID Pengguna:", placeholder="contoh@gmail.com atau username", key="login_uid")
                    in_pin = st.text_input("PIN / Password (Minimal 4 Karakter):", type="password", placeholder="****", key="login_pin")
                    
                    if st.button("🚀 Masuk Sekarang", type="primary", use_container_width=True, key="btn_do_login"):
                        success, res = authenticate_user(in_uid, in_pin)
                        if success:
                            st.session_state["user"] = res
                            st.session_state["nutrition_data"] = None
                            st.query_params["u"] = res["user_id"]
                            st.query_params["s"] = create_session_token(res["user_id"])
                            st.query_params["auth"] = "local"
                            _mark_db_mutated()
                            st.toast(f"Selamat datang kembali, {res['display_name']}!")
                            st.rerun()
                        else:
                            st.error(f"❌ {res}")
                            
                    st.caption("🔒 Data diary & berat badan Anda dilindungi PIN terenkripsi.")
                    
                with sub_reg:
                    st.markdown("##### 📝 Buat Akun Open Beta (Gratis)")
                    reg_uid = st.text_input("Email / ID Unik:", placeholder="contoh@gmail.com / nama_kamu", key="reg_uid")
                    reg_name = st.text_input("Nama Panggilan:", placeholder="misal: Dwi Mey", key="reg_name")
                    reg_pin = st.text_input("Buat PIN / Password Baru:", type="password", placeholder="Minimal 4 digit", key="reg_pin")
                    
                    c_r1, c_r2 = st.columns(2)
                    with c_r1:
                        reg_gender = st.selectbox("Gender:", ["Pria", "Wanita"], key="reg_gen")
                        reg_bb = st.number_input("Berat Badan (kg):", value=65.0, step=1.0, key="reg_bb")
                    with c_r2:
                        reg_age = st.number_input("Usia (thn):", value=25, step=1, key="reg_age")
                        reg_tb = st.number_input("Tinggi Badan (cm):", value=170.0, step=1.0, key="reg_tb")
                        
                    reg_focus = st.selectbox("Fokus Pemantauan:", FOCUS_GOALS, key="reg_focus")
                    reg_goal = st.selectbox("Target Kalori:", [
                        "🔥 Turunkan Berat Badan (Defisit Sehat -400 kkal)",
                        "⚖️ Jaga Berat Badan Ideal (Maintenance)",
                        "💪 Tambah Berat / Massa Otot (Surplus +400 kkal)"
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
                    
                    st.markdown(f"""
                    <div style="background: rgba(16, 185, 129, 0.12); border-left: 3px solid #10b981; padding: 0.5rem 0.8rem; border-radius: 8px; margin: 0.5rem 0; font-size: 0.85rem;">
                        🎯 Rekomendasi Target Tubuhmu: <strong>{auto_target} kkal/hari</strong> (BMR: {round(calc_bmr)} kkal)
                    </div>
                    """, unsafe_allow_html=True)
                    
                    reg_target = st.number_input("Target Kalori Disepakati (kkal/hari):", min_value=1000, max_value=4000, value=int(auto_target), step=50, key="reg_kcal")
                    
                    if st.button("✨ Daftar & Mulai Catat Gratis", type="primary", use_container_width=True, key="btn_do_reg"):
                        if not reg_pin.strip() or len(reg_pin.strip()) < 4:
                            st.error("PIN / Password minimal 4 karakter untuk melindungi akun Anda.")
                        else:
                            success, res = register_user(
                                reg_uid, reg_name, reg_pin,
                                gender=reg_gender, bb=reg_bb, tb=reg_tb, age=int(reg_age),
                                target_kcal=float(reg_target), focus_goal=reg_focus, timezone_offset=8
                            )
                            if success:
                                st.session_state["user"] = res
                                st.session_state["nutrition_data"] = None
                                st.query_params["u"] = res["user_id"]
                                st.query_params["s"] = create_session_token(res["user_id"])
                                st.query_params["auth"] = "local"
                                _mark_db_mutated()
                                st.balloons()
                                st.toast("🎉 Akun Open Beta berhasil dibuat! Akses 5x scan foto/hari aktif.")
                                st.rerun()
                            else:
                                st.error(f"❌ {res}")
        
        with c_acc2:
            with st.popover("🎟️ Akses Open Beta", use_container_width=True):
                st.markdown("### 🧪 **Program Uji Coba (Open Beta)**")
                st.caption("Saat ini seluruh fitur dibuka gratis untuk teman & komunitas uji coba tanpa pembayaran apa pun.")
                
                if is_admin:
                    st.success("🌟 **Status: FOUNDER / ADMIN (Unlimited)**")
                elif current_user["user_id"] == "Tamu (Demo)":
                    st.info(f"🌱 **Mode Demo Aktif:** `{scan_status['scans_today']}/{scan_status['max_scans']}` scan foto hari ini.")
                    st.markdown("""
                    Daftar akun gratis (15 detik) untuk menikmati:
                    - 📸 **5x Scan Foto AI / hari** (3x makan berat + 2x jajan)
                    - ⚖️ **Pelacak Berat Badan & Streak Harian**
                    - 🩺 **Mode Fokus Klinis** (Diet / Bumil / DM / Hipertensi)
                    - ✍️ **Catat Teks AI, Barcode, & 1-Klik Menu** *(Unlimited)*
                    """)
                else:
                    sisa_scan = max(0, scan_status["max_scans"] - scan_status["scans_today"])
                    st.success(f"🎉 **Akun Beta Aktif!** Sisa scan foto hari ini: **{sisa_scan} / {scan_status['max_scans']}x**")
                    st.markdown("""
                    **Fasilitas Akun Beta Anda (Gratis):**
                    - 📸 **5x Scan Foto Makanan AI / hari** (3x makan berat + 2x camilan)
                    - ✍️ **Catat Teks, 1-Klik Menu Harian, & Barcode** *(Unlimited)*
                    - ⚖️ **Grafik Berat Badan, Streak Harian, & Fokus Klinis**
                    """)

# Smart Hero Banner untuk Pengunjung Tamu (Open Beta Ramah Tanpa Tagihan)
if current_user["user_id"] == "Tamu (Demo)":
    with st.container(border=True):
        c_hero_txt, c_hero_act = st.columns([2.3, 1.2], vertical_alignment="center")
        with c_hero_txt:
            st.markdown("""
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
                <span style="background: #10b981; color: #ffffff; font-size: 0.72rem; font-weight: 800; padding: 0.18rem 0.55rem; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.04em;">Open Beta Gratis</span>
                <span style="color: #059669; font-size: 0.85rem; font-weight: 700;">🥗 1.301+ Data Lab TKPI Kemenkes + Open Food Facts</span>
            </div>
            <h3 style="margin: 0.2rem 0; font-size: 1.25rem; font-weight: 800; letter-spacing: -0.01em;">
                Foto Piringmu, Ketahui Kalori & Gizi Nyata Tanpa Ribet
            </h3>
            <p style="margin: 0; font-size: 0.88rem; opacity: 0.85; line-height: 1.45;">
                Sedang dalam mode demo. <strong>Buat akun gratis (cukup nama & 4 digit PIN)</strong> untuk mengunci riwayat makan, grafik berat badan, streak harian, dan kuota <strong>5x scan foto AI per hari</strong>.
            </p>
            """, unsafe_allow_html=True)
            
        with c_hero_act:
            with st.popover("🚀 Buat Akun Gratis (15 Detik)", type="primary", use_container_width=True):
                st.markdown("##### 📝 Pendaftaran Akun Beta")
                st.caption("Hitung target kalori otomatis & simpan riwayat Anda:")
                h_uid = st.text_input("Email / ID Unik:", placeholder="contoh@gmail.com / nama_kamu", key="h_reg_uid")
                h_name = st.text_input("Nama Panggilan:", placeholder="misal: Dwi Mey", key="h_reg_name")
                h_pin = st.text_input("Buat PIN / Password Baru:", type="password", placeholder="Minimal 4 digit", key="h_reg_pin")
                
                hc_1, hc_2 = st.columns(2)
                with hc_1:
                    h_gender = st.selectbox("Gender:", ["Pria", "Wanita"], key="h_reg_gen")
                    h_bb = st.number_input("Berat (kg):", value=65.0, step=1.0, key="h_reg_bb")
                with hc_2:
                    h_age = st.number_input("Usia (thn):", value=25, step=1, key="h_reg_age")
                    h_tb = st.number_input("Tinggi (cm):", value=170.0, step=1.0, key="h_reg_tb")
                    
                h_focus = st.selectbox("Fokus Kesehatan:", FOCUS_GOALS, key="h_reg_focus")
                h_goal = st.selectbox("Tujuan Program:", [
                    "🔥 Turunkan Berat Badan (Defisit Sehat -400 kkal)",
                    "⚖️ Jaga Berat Badan Ideal (Maintenance)",
                    "💪 Tambah Berat / Massa Otot (Surplus +400 kkal)"
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
                
                st.markdown(f"""
                <div style="background: rgba(16, 185, 129, 0.12); border-left: 3px solid #10b981; padding: 0.5rem 0.8rem; border-radius: 8px; margin: 0.5rem 0; font-size: 0.85rem;">
                    🎯 Target Kalori Dihitung: <strong>{h_target} kkal/hari</strong> (BMR: {round(h_bmr)} kkal)
                </div>
                """, unsafe_allow_html=True)
                
                h_custom_target = st.number_input("Target Kalori Awal (kkal/hari):", min_value=1000, max_value=4000, value=int(h_target), step=50, key="h_reg_target")
                
                if st.button("✨ Buat Akun Gratis Sekarang", type="primary", use_container_width=True, key="h_btn_submit"):
                    if not h_uid.strip() or len(h_pin.strip()) < 4:
                        st.error("ID / Email wajib diisi dan PIN minimal 4 karakter!")
                    else:
                        success, res = register_user(
                            h_uid, h_name, h_pin,
                            gender=h_gender, bb=h_bb, tb=h_tb,
                            age=int(h_age), target_kcal=float(h_custom_target),
                            focus_goal=h_focus, timezone_offset=8
                        )
                        if success:
                            st.session_state["user"] = res
                            st.query_params["u"] = res["user_id"]
                            st.query_params["s"] = create_session_token(res["user_id"])
                            st.query_params["auth"] = "local"
                            _mark_db_mutated()
                            st.balloons()
                            st.toast("🎉 Akun berhasil dibuat! Akses 5x scan foto/hari aktif untuk Anda.")
                            st.rerun()
                        else:
                            st.error(f"❌ {res}")

# Deteksi Gemini API Key (Global)
api_key = os.environ.get("GEMINI_API_KEY", "")
if not api_key:
    try:
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

# Navigasi Menu Atas (Mobile-Friendly, Ringkas, & Muat 1 Layar HP Tanpa Geser)
tab_diary, tab_scanner, tab_sources, tab_guide = st.tabs([
    "📊 Hari Ini",
    "📸 Catat",
    "📚 Database",
    "❓ Bantuan"
])

# Inisialisasi Tanggal Aktif Dashboard berdasarkan Zona Waktu Lokal Pengguna (WITA default)
local_now = get_local_now(user_tz)
if "selected_diary_date" not in st.session_state:
    st.session_state["selected_diary_date"] = local_now.date()

active_diary_date = st.session_state["selected_diary_date"]
active_diary_date_str = active_diary_date.strftime("%Y-%m-%d")

# Ambil statistik riwayat & streak akun dari single-bundle dashboard cache (hemat query berulang)
stats = dash_bundle["stats"]
streak_days = dash_bundle["streak_days"]
target_kcal = float(st.session_state["user"].get("daily_calorie_target") or 2000.0)
today_kcal = stats["today_totals"]["energy_kcal"]
pct_today_actual = round((today_kcal / target_kcal) * 100, 1) if target_kcal > 0 else 0.0
pct_today_bar = min(pct_today_actual / 100.0, 1.0)
macro_targets = compute_macro_targets(target_kcal, user_focus)

# ================= TAB 1: DASHBOARD REKAPAN KALORI =================
with tab_diary:
    # Bar Navigasi Tanggal Cepat (Hari Ini, Kemarin, Kalender)
    c_date1, c_date2, c_date3, c_date4 = st.columns([1.2, 1.2, 1.6, 2], vertical_alignment="center")
    today_dt = local_now.date()
    yesterday_dt = today_dt - timedelta(days=1)
    
    with c_date1:
        if st.button("📍 Hari Ini", use_container_width=True, type="primary" if active_diary_date == today_dt else "secondary"):
            st.session_state["selected_diary_date"] = today_dt
            st.rerun()
    with c_date2:
        if st.button("⏮️ Kemarin", use_container_width=True, type="primary" if active_diary_date == yesterday_dt else "secondary"):
            st.session_state["selected_diary_date"] = yesterday_dt
            st.rerun()
    with c_date3:
        pick_d = st.date_input("Pilih Tanggal:", value=active_diary_date, max_value=today_dt + timedelta(days=7), key="dash_datepicker", label_visibility="collapsed")
        if pick_d != active_diary_date:
            st.session_state["selected_diary_date"] = pick_d
            st.rerun()
    with c_date4:
        day_id = {"Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu", "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"}.get(active_diary_date.strftime('%A'), active_diary_date.strftime('%A'))
        tz_short = {7: "WIB", 8: "WITA", 9: "WIT"}.get(user_tz, "WITA")
        st.markdown(f"<div style='text-align: right; font-weight: 700; font-size: 0.92rem; opacity: 0.85;'>📅 {day_id}, {active_diary_date.strftime('%d/%m/%Y')} ({tz_short})</div>", unsafe_allow_html=True)

    st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

    # Pesan Konfirmasi Penyimpanan Terakhir (Visual Feedback Anti-Bingung)
    if "last_saved_item" in st.session_state and st.session_state["last_saved_item"]:
        saved_info = st.session_state["last_saved_item"]
        st.markdown(f"""
        <div style="background: rgba(16, 185, 129, 0.12); border: 1.5px solid #10b981; border-radius: 16px; padding: 0.9rem 1.2rem; margin-bottom: 1.2rem; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-size: 1.6rem;">✅</span>
                <div>
                    <div style="font-weight: 800; font-size: 0.98rem; color: #10b981;">Tersimpan Permanen ke Buku Harian!</div>
                    <div style="font-size: 0.84rem; opacity: 0.9;"><strong>{saved_info['dish_name']}</strong> ({saved_info['energy_kcal']} kkal) • Sesi <strong>{saved_info['meal_type']}</strong> • Jam {saved_info['saved_at']}</div>
                </div>
            </div>
            <span style="background: #10b981; color: white; font-size: 0.72rem; font-weight: 800; padding: 0.25rem 0.65rem; border-radius: 999px;">DATA AMAN</span>
        </div>
        """, unsafe_allow_html=True)

    # Banner Cincin Aktivitas Kalori Hari Ini (Apple Health Style + Streak & Fokus + Persentase Jujur)
    streak_badge_html = (
        f"<span style='background: rgba(245, 158, 11, 0.16); color: #d97706; padding: 0.4rem 0.9rem; border-radius: 9999px; font-weight: 800; font-size: 0.85rem;'>🔥 Streak {streak_days} Hari</span>"
        if streak_days > 0 else
        "<span style='background: rgba(125, 125, 125, 0.14); padding: 0.4rem 0.9rem; border-radius: 9999px; font-weight: 700; font-size: 0.82rem;'>🌱 Mulai Streak Hari Ini</span>"
    )
    kcal_delta = target_kcal - today_kcal
    budget_text = (
        f"Sisa budget: <strong>{kcal_delta:,.1f} kkal</strong>"
        if kcal_delta >= 0 else
        f"Melebihi target: <strong style='color:#ef4444;'>+{abs(kcal_delta):,.1f} kkal</strong>"
    )
    st.markdown(f"""
    <div class="apple-ring-card">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <div class="ring-title">🎯 Cincin Kalori ({active_diary_date.strftime('%d %B %Y')}) • Fokus: {user_focus}</div>
                <div class="ring-val">{today_kcal:,.1f} <span style="font-size: 1.1rem; color: #64748b; font-weight: 500;">/ {target_kcal:,.0f} kkal</span></div>
                <div class="ring-sub">Tercapai <strong>{pct_today_actual}%</strong> • {budget_text}</div>
            </div>
            <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-top: 0.3rem;">
                {streak_badge_html}
                <span style="background: rgba(16, 185, 129, 0.15); color: #059669; padding: 0.4rem 1rem; border-radius: 9999px; font-weight: 700; font-size: 0.88rem;">
                    {stats['today_totals']['count']} Menu Tercatat
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Progress Bar Lembut
    st.progress(pct_today_bar)

    # 4 Makronutrien Hari Ini + Target Gram Klinis
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #0284c7;">{stats['today_totals']['protein_g']}g <span style="font-size: 0.78rem; opacity: 0.65;">/ {macro_targets['protein_g']}g</span></div>
            <div class="macro-lbl">Protein Hari Ini</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #d97706;">{stats['today_totals']['fat_g']}g <span style="font-size: 0.78rem; opacity: 0.65;">/ {macro_targets['fat_g']}g</span></div>
            <div class="macro-lbl">Lemak Hari Ini</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m3:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #059669;">{stats['today_totals']['carb_g']}g <span style="font-size: 0.78rem; opacity: 0.65;">/ {macro_targets['carb_g']}g</span></div>
            <div class="macro-lbl">Karbohidrat</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m4:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #7c3aed;">{stats['today_totals']['fiber_g']}g <span style="font-size: 0.78rem; opacity: 0.65;">/ {macro_targets['fiber_g']}g</span></div>
            <div class="macro-lbl">Serat</div>
        </div>
        """, unsafe_allow_html=True)

    # Visual Macro Split Ratio Bar (Cal AI Style)
    p_g = stats['today_totals']['protein_g']
    f_g = stats['today_totals']['fat_g']
    c_g = stats['today_totals']['carb_g']
    fib_g = stats['today_totals']['fiber_g']
    sod_mg = stats['today_totals'].get('sodium_mg', 0.0)
    macro_sum = p_g + f_g + c_g
    if macro_sum > 0:
        p_pct = round((p_g / macro_sum) * 100)
        f_pct = round((f_g / macro_sum) * 100)
        c_pct = max(0, 100 - p_pct - f_pct)
        st.markdown(f"""
        <div style="background: rgba(125, 125, 125, 0.06); border: 1px solid rgba(125, 125, 125, 0.14); border-radius: 16px; padding: 0.85rem 1.2rem; margin: 1rem 0;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.45rem; font-size: 0.82rem; font-weight: 700;">
                <span>📊 Rasio Makronutrien Hari Ini</span>
                <span style="opacity: 0.75;">Total Makro: {macro_sum:.1f}g • Natrium: {sod_mg:,.0f} / {macro_targets['sodium_mg']:,.0f} mg</span>
            </div>
            <div style="display: flex; height: 10px; border-radius: 999px; overflow: hidden; margin-bottom: 0.55rem; background: rgba(125, 125, 125, 0.15);">
                <div style="width: {p_pct}%; background: #0284c7;" title="Protein {p_pct}%"></div>
                <div style="width: {f_pct}%; background: #d97706;" title="Lemak {f_pct}%"></div>
                <div style="width: {c_pct}%; background: #059669;" title="Karbohidrat {c_pct}%"></div>
            </div>
            <div style="display: flex; justify-content: space-around; font-size: 0.76rem; font-weight: 700;">
                <span style="color: #0284c7;">● Protein {p_pct}%</span>
                <span style="color: #d97706;">● Lemak {f_pct}%</span>
                <span style="color: #059669;">● Karbo {c_pct}%</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 🧠 Smart Daily Balancer (Beradaptasi dengan Fokus Kesehatan: Diet / Bumil / DM / Hipertensi)
    rem_kcal = max(0.0, target_kcal - today_kcal)
    prot_ratio = 0.25 if "Hamil" in user_focus else 0.22
    target_prot = round((target_kcal * prot_ratio) / 4.0)
    if stats['today_totals']['count'] > 0:
        if "Hipertensi" in user_focus and sod_mg >= 1800.0:
            balancer_msg = f"🧂 <strong>Peringatan Natrium (Hipertensi):</strong> Asupan garam/natrium hari ini sudah mencapai <strong>{sod_mg:,.0f} mg</strong> (mendekati/melewati batas aman 2.000 mg Kemenkes/WHO). Hindari makanan asin, kecap berlebih, & kuah kaldu di jam makan berikutnya!"
            balancer_col = "#ef4444"
        elif "Diabetes" in user_focus and c_g > (target_kcal * 0.55 / 4.0) and fib_g < 15.0:
            balancer_msg = f"🩸 <strong>Kendali Gula & Karbo (DM):</strong> Karbohidrat cukup tinggi (<strong>{c_g}g</strong>) dengan serat masih <strong>{fib_g}g</strong>. Perbanyak sayuran berserat & protein di porsi berikutnya agar lonjakan gula darah tetap landai!"
            balancer_col = "#f59e0b"
        elif "Hamil" in user_focus and p_g < target_prot * 0.6:
            balancer_msg = f"🤰 <strong>Nutrisi Ibu & Janin:</strong> Asupan protein masih <strong>{p_g}g / ~{target_prot}g</strong>. Tambahkan sumber protein hewani (ikan kembung/patin, telur, ayam, atau susu) untuk mendukung pertumbuhan janin!"
            balancer_col = "#0284c7"
        elif p_g < target_prot * 0.5 and rem_kcal > 250:
            balancer_msg = f"🥩 <strong>Asupan Protein Masih Rendah ({p_g}g / target ~{target_prot}g):</strong> Tambahkan <strong>2 butir telur rebus (+12g P)</strong>, <strong>1 potong dada ayam bakar (+28g P)</strong>, atau <strong>tempe/tahu</strong> di jam makan berikutnya agar massa otot tetap terjaga!"
            balancer_col = "#0284c7"
        elif fib_g < 10.0 and rem_kcal > 150:
            balancer_msg = f"🥦 <strong>Serat Pangan Belum Optimal ({fib_g}g / target 25g):</strong> Tambahkan seporsi <strong>sayur bening bayam, capcay, atau 1 buah pepaya/apel</strong> agar pencernaan lancar dan kenyang lebih tahan lama."
            balancer_col = "#10b981"
        elif rem_kcal <= 150 and today_kcal <= target_kcal * 1.05:
            balancer_msg = f"🎯 <strong>Target Harian Hampir Sempurna!</strong> Sisa kuota kalori Anda tinggal <strong>{rem_kcal:.0f} kkal</strong>. Cukup minum air putih atau teh tawar hangat untuk menutup hari ini."
            balancer_col = "#10b981"
        elif today_kcal > target_kcal * 1.05:
            balancer_msg = f"⚡ <strong>Kalori Melewati Target (+{today_kcal - target_kcal:.0f} kkal):</strong> Tidak perlu panik! Cukup jalan kaki santai 20–30 menit sore/malam ini dan kurangi porsi karbohidrat besok pagi."
            balancer_col = "#f59e0b"
        else:
            balancer_msg = f"✨ <strong>Komposisi Makanmu Terjaga Baik!</strong> Sisa budget hari ini <strong>{rem_kcal:.0f} kkal</strong>. Pertahankan porsi protein dan air putih."
            balancer_col = "#10b981"
            
        st.markdown(f"""
        <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.25); border-left: 5px solid {balancer_col}; border-radius: 14px; padding: 0.85rem 1.15rem; margin-bottom: 1rem; font-size: 0.88rem; line-height: 1.45;">
            🧠 <strong>Smart Daily Balancer ({user_focus}):</strong> {balancer_msg}
        </div>
        """, unsafe_allow_html=True)

    # ⚡ Aksi Cepat Catat Makanan Langsung di Dashboard (Seragam: Selalu Preview Dulu, Bebas Salah Sesi/Dobel)
    with st.container(border=True):
        st.markdown("##### ⚡ **Catat Cepat Menu Makan Hari Ini**")
        qc_col1, qc_col2 = st.columns([3.2, 1.3], vertical_alignment="center")
        with qc_col1:
            dash_quick_text = st.text_input(
                "Ketik menu makanan langsung:",
                placeholder="Misal: 1 potong bingka pisang, atau 1 porsi soto ayam + nasi",
                key="dash_quick_input",
                label_visibility="collapsed"
            )
        with qc_col2:
            dash_btn_calc = st.button("🔍 Preview & Hitung", type="primary", use_container_width=True, key="btn_dash_quick")

        # Inovasi 1: Sering Kamu Makan (Otomatis dari Riwayat Akunmu di bundle cache)
        freq_meals = dash_bundle.get("frequent_meals") or []
        if freq_meals:
            st.caption("⭐ **Sering Kamu Makan (1-Klik Preview Porsi 1.0x):**")
            fq_cols = st.columns(3)
            for idx_fq, fq_item in enumerate(freq_meals):
                with fq_cols[idx_fq % 3]:
                    if st.button(f"⭐ {fq_item['dish_name'][:22]} ({fq_item['energy_kcal']:.0f} kkal)", use_container_width=True, key=f"dash_fq_{idx_fq}"):
                        _open_food_preview({
                            "dish_name": fq_item["dish_name"],
                            "confidence": "high",
                            "portion_category": "1 porsi kebiasaan Anda",
                            "serving_reference": "1 porsi normal sesuai catatan sebelumnya",
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
                            "health_tip": "Menu favorit harianmu siap disesuaikan porsi & sesi makannya sebelum disimpan."
                        }, origin_tab="diary")
                        st.rerun()

        # Inovasi 2: Piring Cepat Populer Indonesia (Preview Cepat Tanpa Ketik)
        st.caption("🔥 **Menu Harian Populer (1-Klik Preview Tanpa Ketik):**")
        QUICK_PLATES = [
            ("🍛 Nasi + Telur Dadar", "Nasi Putih + Telur Dadar", {"energy_kcal": 315.0, "protein_g": 11.5, "fat_g": 12.0, "carb_g": 40.0, "fiber_g": 1.0, "sodium_mg": 240.0}),
            ("🍗 Nasi + Ayam Bakar", "Nasi Putih + Ayam Bakar Dada", {"energy_kcal": 385.0, "protein_g": 32.0, "fat_g": 8.5, "carb_g": 43.0, "fiber_g": 1.2, "sodium_mg": 380.0}),
            ("🍜 Bakso Kuah Komplit", "Semangkuk Bakso Sapi Kuah", {"energy_kcal": 340.0, "protein_g": 18.5, "fat_g": 11.0, "carb_g": 41.0, "fiber_g": 2.0, "sodium_mg": 680.0}),
            ("🥗 Gado-Gado Telur", "Gado-Gado Lontong + Telur Rebus", {"energy_kcal": 410.0, "protein_g": 16.0, "fat_g": 18.0, "carb_g": 46.0, "fiber_g": 5.5, "sodium_mg": 420.0}),
            ("☕ Kopi Susu Aren", "Es Kopi Susu Gula Aren", {"energy_kcal": 175.0, "protein_g": 4.2, "fat_g": 5.5, "carb_g": 27.0, "fiber_g": 0.0, "sodium_mg": 65.0}),
            ("🥚 2 Telur Rebus", "2 Butir Telur Ayam Rebus", {"energy_kcal": 154.0, "protein_g": 12.6, "fat_g": 10.6, "carb_g": 1.1, "fiber_g": 0.0, "sodium_mg": 140.0}),
        ]
        qp_cols = st.columns(3)
        for idx_qp, (qp_label, qp_name, qp_tot) in enumerate(QUICK_PLATES):
            with qp_cols[idx_qp % 3]:
                if st.button(qp_label, use_container_width=True, key=f"dash_qp_{idx_qp}"):
                    _open_food_preview({
                        "dish_name": qp_name,
                        "confidence": "high",
                        "portion_category": "1 porsi standar",
                        "serving_reference": "1 porsi standar URT",
                        "user_caption": "Piring Cepat 1-Klik",
                        "components": [{
                            "name": qp_name,
                            "weight_g": 100.0,
                            "energy_kcal_per_100g": qp_tot["energy_kcal"],
                            "protein_g_per_100g": qp_tot["protein_g"],
                            "fat_g_per_100g": qp_tot["fat_g"],
                            "carb_g_per_100g": qp_tot["carb_g"],
                            "fiber_g_per_100g": qp_tot["fiber_g"],
                            "sodium_mg_per_100g": qp_tot["sodium_mg"],
                            "custom_override": True,
                            "source_label": "Standar Menu Populer"
                        }],
                        "health_tip": "Pilih ukuran porsi & sesi makan di bawah lalu klik Simpan ke Buku Harian."
                    }, origin_tab="diary")
                    st.rerun()

        if dash_btn_calc:
            if not dash_quick_text.strip():
                st.warning("Ketikkan nama menu makanan terlebih dahulu.")
            elif not api_key:
                st.error("⚠️ API Key belum disetel di Secrets.")
            else:
                with st.spinner("Menghitung estimasi nutrisi..."):
                    try:
                        res = analyze_food_text(dash_quick_text.strip(), api_key=api_key)
                        res["user_caption"] = dash_quick_text.strip()
                        _open_food_preview(res, origin_tab="diary")
                        st.toast("✅ Preview siap! Pilih porsi & waktu makan di bawah sebelum disimpan.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal menganalisis makanan: {e}")

    if st.session_state.get("nutrition_data"):
        if st.session_state.get("preview_origin_tab") == "diary":
            render_nutrition_preview_card("diary", current_user, active_diary_date_str, user_tz, is_admin)
        else:
            st.info(f"🍽️ Sedang ada Preview terbuka untuk **{st.session_state['nutrition_data'].get('dish_name')}** di tab **{st.session_state.get('preview_origin_tab', 'scanner').title()}**.")

    # Widget Pelacak Air Minum Harian & Pelacak Berat Badan
    water_data = dash_bundle.get("water_data") or {"glasses": 0, "target": 8, "ml": 0}
    water_pct = min(1.0, water_data["glasses"] / max(1, water_data["target"]))
    
    c_track1, c_track2 = st.columns([1.15, 1], gap="medium")
    with c_track1:
        with st.container(border=True):
            col_w1, col_w3 = st.columns([2.1, 1], vertical_alignment="center")
            with col_w1:
                st.markdown(f"💧 **Air Minum:** `{water_data['glasses']}/{water_data['target']} Gelas` ({water_data['ml']} ml)")
                st.progress(water_pct)
                st.caption("Target 8 gelas (2.000 ml) untuk metabolisme optimal.")
            with col_w3:
                col_b1, col_b2 = st.columns(2)
                with col_b1:
                    if st.button("➕", use_container_width=True, key="btn_add_water", help="Tambah 1 gelas air"):
                        log_water_intake(st.session_state["user"]["user_id"], 1, tz_offset=user_tz)
                        _mark_db_mutated()
                        st.toast("💧 +1 Gelas air dicatat!")
                        st.rerun()
                with col_b2:
                    if st.button("➖", use_container_width=True, key="btn_sub_water", help="Kurangi 1 gelas air"):
                        log_water_intake(st.session_state["user"]["user_id"], -1, tz_offset=user_tz)
                        _mark_db_mutated()
                        st.rerun()

    with c_track2:
        with st.container(border=True):
            w_hist = dash_bundle.get("weight_history") or []
            latest_w = w_hist[-1]["weight_kg"] if w_hist else float(current_user.get("weight_kg") or 65.0)
            cw_1, cw_2 = st.columns([1.8, 1.1], vertical_alignment="bottom")
            with cw_1:
                in_w = st.number_input("⚖️ Timbang Berat Hari Ini (kg):", min_value=20.0, max_value=250.0, value=float(latest_w), step=0.1, key="dash_weight_in")
            with cw_2:
                if st.button("💾 Catat BB", use_container_width=True, key="btn_save_weight"):
                    log_weight_entry(st.session_state["user"]["user_id"], in_w, tz_offset=user_tz, recorded_date=active_diary_date_str)
                    st.session_state["user"]["weight_kg"] = in_w
                    _mark_db_mutated()
                    st.toast(f"⚖️ Berat badan {in_w:.1f} kg disimpan!")
                    st.rerun()
            if len(w_hist) >= 2:
                delta_w = round(w_hist[-1]["weight_kg"] - w_hist[0]["weight_kg"], 1)
                sign_w = "+" if delta_w > 0 else ""
                st.caption(f"📈 Tercatat {len(w_hist)} kali • Perubahan total: **{sign_w}{delta_w} kg** ({w_hist[0]['weight_kg']} → {w_hist[-1]['weight_kg']} kg)")
            else:
                st.caption("Catat berat badan secara rutin 1–2x seminggu untuk memantau grafik tren Anda.")

    if w_hist and len(w_hist) >= 2:
        with st.expander("📈 **Lihat Grafik Progres Berat Badan**", expanded=False):
            df_w = pd.DataFrame(w_hist)
            df_w["recorded_date"] = pd.to_datetime(df_w["recorded_date"]).dt.strftime("%d/%m")
            st.line_chart(df_w.set_index("recorded_date")["weight_kg"], color="#0284c7")

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Pembagian 2 Kolom: Mingguan & Bulanan
    col_week, col_month = st.columns([1.5, 1], gap="large")
    
    with col_week:
        st.markdown("### 📊 **Tren 7 Hari & Proyeksi Defisit/Surplus**")
        if stats["weekly_data"]:
            df_week = pd.DataFrame(stats["weekly_data"])
            df_week["day"] = pd.to_datetime(df_week["day"]).dt.strftime("%a (%d/%m)")
            st.bar_chart(df_week.set_index("day")["total_kcal"], color="#10b981")
            
            # Hitung rata-rata & proyeksi berat badan
            avg_weekly_kcal = df_week["total_kcal"].mean()
            daily_diff = avg_weekly_kcal - target_kcal
            # 7.700 kkal = 1 kg lemak tubuh
            weekly_weight_change = (daily_diff * 7) / 7700.0
            
            if daily_diff < -100:
                st.success(f"📉 **Proyeksi Diet:** Rata-rata asupanmu {avg_weekly_kcal:,.0f} kkal (Defisit {abs(daily_diff):,.0f} kkal/hari). Diproyeksikan turun **~{abs(weekly_weight_change):.2f} kg lemak** minggu ini!")
            elif daily_diff > 100:
                st.warning(f"📈 **Proyeksi Surplus:** Rata-rata asupanmu {avg_weekly_kcal:,.0f} kkal (Surplus {daily_diff:,.0f} kkal/hari). Diproyeksikan naik **~{weekly_weight_change:.2f} kg** minggu ini.")
            else:
                st.info(f"⚖️ **Pemeliharaan (Maintenance):** Asupanmu seimbang mendekati target ({avg_weekly_kcal:,.0f} kkal). Berat badan diproyeksikan stabil.")
        else:
            st.info("Belum ada catatan makan dalam 7 hari terakhir. Mulai catat di tab sebelah!")

    with col_month:
        st.markdown("### 🗓️ **Rekapan 30 Hari (Bulanan)**")
        m_data = stats["monthly_summary"]
        st.markdown(f"""
        <div class="apple-ring-card">
            <div class="ring-title">Total Kalori 30 Hari</div>
            <div class="ring-val" style="color: #0284c7;">{m_data['total_kcal']:,.0f} <span style="font-size: 1rem; opacity: 0.7; font-weight: 500;">kkal</span></div>
            <hr style="margin: 0.8rem 0; border: none; border-top: 1px solid rgba(125, 125, 125, 0.2);">
            <p style="margin: 0.3rem 0; opacity: 0.9;">📅 <strong>Hari Aktif Mencatat:</strong> {m_data['active_days']} hari</p>
            <p style="margin: 0.3rem 0; opacity: 0.9;">🍽️ <strong>Total Menu Masuk:</strong> {m_data['total_meals']} porsi</p>
            <p style="margin: 0.3rem 0; opacity: 0.9;">⚡ <strong>Rata-rata Harian:</strong> {(m_data['total_kcal'] / max(1, m_data['active_days'])):,.0f} kkal/hari</p>
        </div>
        """, unsafe_allow_html=True)

    # Riwayat Makan Hari Ini, Pembersih Duplikat, Salin Kemarin, & Edit Inline 2-Detik
    st.markdown("### 📝 **Buku Harian Makan Hari Ini**")

    dup_ids = find_duplicate_meals(stats["today_meals"])
    if dup_ids:
        c_dup1, c_dup2 = st.columns([2.6, 1.4], vertical_alignment="center")
        with c_dup1:
            st.warning(f"⚠️ Terdeteksi **{len(dup_ids)} catatan menu kembar** di hari ini (misal tercatat ganda sebelumnya).")
        with c_dup2:
            if st.button(f"🧹 Rapikan Menu Kembar ({len(dup_ids)})", type="primary", use_container_width=True, key="btn_clean_dups"):
                del_cnt = remove_duplicate_meals_for_date(st.session_state["user"]["user_id"], active_diary_date_str)
                _mark_db_mutated()
                st.toast(f"🧹 Berhasil merapikan {del_cnt} catatan kembar!")
                st.rerun()

    yest_for_copy = (active_diary_date - timedelta(days=1)).strftime("%Y-%m-%d")

    # Tombol Bagikan ke WhatsApp & Ekspor
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
            st.markdown(f"""
            <a href="{wa_url}" target="_blank" style="text-decoration: none;">
                <div style="background-color: #25d366; color: white; padding: 0.55rem 1rem; border-radius: 12px; font-weight: 700; text-align: center; box-shadow: 0 4px 12px rgba(37, 211, 102, 0.25);">
                    📲 Bagikan Laporan ke WhatsApp
                </div>
            </a>
            """, unsafe_allow_html=True)
            
        with col_share2:
            # Unduh CSV
            df_export = pd.DataFrame(stats["today_meals"])
            if not df_export.empty:
                cols_to_export = [c for c in ["logged_at", "meal_type", "dish_name", "energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "sodium_mg", "photo_caption"] if c in df_export.columns]
                csv_data = df_export[cols_to_export].to_csv(index=False).encode('utf-8')
                st.download_button("📥 Unduh Rekap (CSV/Excel)", data=csv_data, file_name=f"nutrisi_harian_{active_diary_date.strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Kelompokkan per Waktu Makan Terstruktur
        MEAL_ORDER = [
            ("Sarapan", "🌅 Sarapan Pagi"),
            ("Makan Siang", "☀️ Makan Siang"),
            ("Makan Malam", "🌙 Makan Malam"),
            ("Camilan", "🍪 Camilan & Minuman"),
        ]
        
        grouped_meals = {}
        for m in stats["today_meals"]:
            mtype = _normalize_meal_key(m.get("meal_type"))
            if mtype not in grouped_meals:
                grouped_meals[mtype] = []
            grouped_meals[mtype].append(m)

        # Urutan tampil logis: Sarapan -> Siang -> Malam -> Camilan -> Lainnya
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
            
            label_display = dict(MEAL_ORDER).get(mtype, f"🍽️ {mtype}")

            with st.container(border=True):
                c_mhead1, c_mhead2 = st.columns([2, 1], vertical_alignment="center")
                with c_mhead1:
                    st.markdown(f"#### **{label_display}**")
                with c_mhead2:
                    st.markdown(f"<div style='text-align: right; font-weight: 800; font-size: 1.05rem; color: #10b981;'>{subtotal_kcal:,.1f} kkal</div>", unsafe_allow_html=True)
                    st.caption(f"<div style='text-align: right;'>P: {subtotal_p:.1f}g • L: {subtotal_f:.1f}g • K: {subtotal_c:.1f}g</div>", unsafe_allow_html=True)

                st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

                for m in meals_in_group:
                    try:
                        time_str = datetime.strptime(m["logged_at"][:19], "%Y-%m-%d %H:%M:%S").strftime("%H:%M") if " " in str(m["logged_at"]) else str(m["logged_at"])
                    except Exception:
                        time_str = str(m["logged_at"])[11:16] or str(m["logged_at"])
                    is_just_saved = ("last_saved_item" in st.session_state and st.session_state["last_saved_item"] and st.session_state["last_saved_item"].get("id") == m["id"])
                    saved_badge = '<span style="background: rgba(16,185,129,0.18); color: #10b981; font-size: 0.68rem; font-weight: 800; padding: 0.15rem 0.5rem; border-radius: 999px; border: 1px solid rgba(16,185,129,0.3); margin-left: 6px;">🟢 BARU DISIMPAN</span>' if is_just_saved else ''

                    col_row1, col_row2, col_row3, col_row4 = st.columns([3.0, 1.9, 0.55, 0.55], vertical_alignment="center")
                    with col_row1:
                        mult_lbl = f" • {m.get('portion_multiplier', 1.0)}x" if float(m.get("portion_multiplier") or 1.0) != 1.0 else ""
                        st.markdown(f"**{m['dish_name']}**{mult_lbl} {saved_badge}", unsafe_allow_html=True)
                        sub_cap = f"_{m['photo_caption']}_" if m['photo_caption'] else ""
                        st.caption(f"🕒 {time_str} {sub_cap}")
                    with col_row2:
                        st.markdown(f"**{m['energy_kcal']} kkal**")
                        st.caption(f"P: {m['protein_g']}g • L: {m['fat_g']}g • K: {m['carb_g']}g")
                    with col_row3:
                        with st.popover("✏️", use_container_width=True, help="Ubah waktu makan atau porsi"):
                            st.markdown(f"##### ✏️ Edit: **{m['dish_name']}**")
                            cur_mt = _normalize_meal_key(m.get("meal_type"))
                            mt_idx = EDIT_MEAL_CHOICES.index(cur_mt) if cur_mt in EDIT_MEAL_CHOICES else 1
                            ed_mt = st.selectbox("Pindah Waktu Makan:", EDIT_MEAL_CHOICES, index=mt_idx, key=f"ed_mt_{m['id']}")
                            cur_mult = _closest_portion_opt(m.get("portion_multiplier") or 1.0)
                            ed_mult = st.select_slider(
                                "Ubah Porsi:",
                                options=PORTION_OPTIONS,
                                value=cur_mult,
                                format_func=lambda x: PORTION_LABELS[x],
                                key=f"ed_mult_{m['id']}"
                            )
                            if st.button("💾 Simpan Perubahan", type="primary", use_container_width=True, key=f"btn_ed_save_{m['id']}"):
                                res_sc = scale_meal_log_portion(m["id"], st.session_state["user"]["user_id"], ed_mult, new_meal_type=ed_mt)
                                if res_sc:
                                    st.session_state["last_saved_item"] = res_sc
                                _mark_db_mutated()
                                st.toast(f"✅ {m['dish_name']} diperbarui ({ed_mt}, {ed_mult}x)!")
                                st.rerun()
                    with col_row4:
                        if st.button("🗑️", key=f"del_{m['id']}", help="Hapus menu ini", use_container_width=True):
                            delete_meal_log(m["id"], st.session_state["user"]["user_id"])
                            _mark_db_mutated()
                            st.toast("Catatan makanan berhasil dihapus.")
                            st.rerun()
    else:
        st.markdown("""
        <div style="background: rgba(125, 125, 125, 0.05); border: 1.5px dashed rgba(125, 125, 125, 0.2); border-radius: 18px; padding: 2rem 1rem; text-align: center; margin: 1.5rem 0;">
            <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🥗</div>
            <div style="font-weight: 700; font-size: 1.05rem; margin-bottom: 0.3rem;">Buku Harian Masih Kosong Hari Ini</div>
            <div style="font-size: 0.88rem; opacity: 0.75; max-width: 450px; margin: 0 auto;">
                Gunakan kotak <strong>Catat Cepat</strong> di atas, salin menu kemarin, atau buka tab <strong>📸 Catat</strong> untuk memotret makananmu.
            </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("📋 Salin Daftar Menu dari Kemarin", use_container_width=True, key="btn_copy_yesterday_empty"):
            cnt_cp = copy_meals_from_date(st.session_state["user"]["user_id"], yest_for_copy, active_diary_date_str, tz_offset=user_tz)
            if cnt_cp > 0:
                _mark_db_mutated()
                st.toast(f"📋 Berhasil menyalin {cnt_cp} menu dari kemarin ({yest_for_copy})!")
                st.rerun()
            else:
                st.info("Belum ada catatan makan kemarin untuk disalin.")

# ================= TAB 2: CATAT MAKANAN BARU (SIMPEL, 3 SUB-TAB MUAT 1 LAYAR HP) =================
with tab_scanner:
    if not api_key:
        st.warning("⚠️ **Mode Offline Lab Aktif (API Key Belum Disetel di Streamlit Secrets)**")
        st.info("Pencarian teks database lab (1.300+ pangan), scan barcode Open Food Facts, & input manual tetap berfungsi 100%. Untuk mengaktifkan Vision AI scan foto piring, tambahkan `GEMINI_API_KEY` di menu Secrets Streamlit Cloud.")

    subtab_foto, subtab_teks, subtab_barcode = st.tabs([
        "📸 Foto Piring",
        "✍️ Ketik & Menu Cepat",
        "🏷️ Barcode & Manual"
    ])
    
    with subtab_foto:
        st.markdown("##### 📸 **Foto Makanan dari Galeri atau Kamera HP**")
        st.caption("Di HP Android/iPhone, klik tombol **Browse files** di bawah untuk langsung memilih **Kamera** atau **Galeri Foto**.")
        c_up1, c_up2 = st.columns([1.2, 1], gap="large")
        with c_up1:
            up_file = st.file_uploader("Pilih atau jepret foto piring makanan:", type=["jpg", "jpeg", "png", "webp"], key="scan_foto")
            with st.expander("📷 **Ingin Membuka Viewfinder Kamera Langsung di Browser? Klik di Sini**", expanded=False):
                cam_file = st.camera_input("Arahkan kamera ke piring makanan:")
                
            active_img_file = up_file or cam_file
            if active_img_file:
                im = Image.open(active_img_file)
                st.image(im, caption="Foto Makanan Siap Dianalisis", use_container_width=True)
                p_caption = st.text_input("💬 Catatan / Keterangan (Opsional):", placeholder="Contoh: Bumbu kacang dipisah / ayam tanpa kulit", key="f_cap")
            else:
                p_caption = ""
        with c_up2:
            if active_img_file:
                st.markdown("#### Siap Menganalisis?")
                st.caption("AI memindai porsi perorangan URT & mencocokkan ke 1.300+ data lab TKPI Kemenkes. Hasil akan tampil sebagai **Preview** terlebih dahulu agar Anda bisa cek porsi & sesi makan.")

                if not scan_status["can_scan"]:
                    max_sc = scan_status["max_scans"]
                    if current_user["user_id"] == "Tamu (Demo)":
                        st.warning(f"⚠️ **Batas Scan Foto Mode Demo Tercapai ({max_sc}/{max_sc} Hari Ini).**")
                        st.info("Buat akun gratis dalam 15 detik di bagian atas untuk membuka **5x Scan Foto AI/hari** (3x makan berat + 2x jajan) atau gunakan tab **✍️ Ketik & Menu Cepat** sepuasnya!")
                    else:
                        st.warning(f"⚠️ **Kuota Scan Foto Hari Ini Tercapai ({max_sc}/{max_sc} — 3x Makan Berat & 2x Jajan).**")
                        st.info("Jangan khawatir! Anda tetap bisa mencatat **sepuasnya tanpa batas** melalui tab **✍️ Ketik & Menu Cepat**, **1-Klik Menu Harian**, atau **🏷️ Barcode & Manual**.")
                else:
                    if st.button("🔍 Cek & Hitung Gizi Foto", type="primary", use_container_width=True, key="btn_foto"):
                        with st.spinner("Menganalisis visual foto makanan..."):
                            try:
                                res = analyze_food_image(im, caption=p_caption, api_key=api_key)
                                res["user_caption"] = p_caption or "Foto Piring"
                                record_scan_usage(current_user["user_id"], tz_offset=user_tz)
                                _mark_db_mutated()
                                _open_food_preview(res, origin_tab="scanner")
                                st.toast("🔍 Foto berhasil dianalisis! Cek porsi & pilih waktu makan di bawah sebelum Simpan.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal memproses gambar: {e}")
            else:
                st.info("💡 **Tips Praktis:** Foto piring makan dari atas agar semua lauk, nasi, dan sayuran tampak jelas dalam 1 bingkai.")

    with subtab_teks:
        st.markdown("##### ✍️ **Ketik Menu Makanan atau Pilih Menu Cepat 1-Klik**")
        t_input = st.text_area("Tuliskan apa yang kamu makan:", placeholder="Contoh: 1 piring gado-gado lontong pakai telur rebus dan bumbu kacang", height=90)
        if st.button("🔍 Hitung Nutrisi Menu", type="primary", use_container_width=True, key="btn_teks"):
            if not api_key:
                st.error("⚠️ API Key belum terkonfigurasi. Silakan periksa pengaturan di sidebar atau secrets.")
            elif not t_input.strip():
                st.warning("Silakan tulis menu makanan terlebih dahulu.")
            else:
                with st.spinner("Menghitung nilai nutrisi dari database lab..."):
                    try:
                        res = analyze_food_text(t_input, api_key=api_key)
                        res["user_caption"] = t_input
                        _open_food_preview(res, origin_tab="scanner")
                        st.toast("✅ Analisis berhasil! Lihat Preview di bawah sebelum Simpan.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal memproses teks: {e}")

        st.markdown("---")
        st.caption("⚡ **Malas Mengetik? Sentuh Menu Populer Indonesia di Bawah Ini:**")
        PRESET_MENUS = [
            ("🍛 Nasi Goreng Telur", "Nasi Goreng + Telur Ceplok", 180.0, 485.0, 16.5, 18.0, 62.0, 2.2),
            ("🍗 Ayam Geprek + Nasi", "Nasi Putih + Ayam Geprek Sambal", 250.0, 560.0, 29.0, 24.0, 56.0, 2.0),
            ("🍲 Soto Ayam + Nasi", "Soto Ayam Kuah Bening + Nasi Putih", 300.0, 395.0, 22.0, 11.5, 49.0, 1.8),
            ("🐟 Pecel Lele + Nasi", "Nasi Putih + Lele Goreng + Lalapan", 240.0, 430.0, 24.5, 16.0, 46.0, 2.5),
            ("🍢 Sate Ayam 10 Tusuk", "Sate Ayam 10 Tusuk + Bumbu Kacang", 180.0, 365.0, 31.0, 19.5, 16.0, 1.5),
            ("🍌 Pisang + Susu", "1 Buah Pisang Ambon + 1 Gelas Susu", 250.0, 235.0, 8.5, 6.0, 37.0, 2.8),
        ]
        pm_cols = st.columns(3)
        for idx_pm, (pm_btn, pm_title, pm_w, pm_k, pm_p, pm_f, pm_c, pm_fib) in enumerate(PRESET_MENUS):
            with pm_cols[idx_pm % 3]:
                if st.button(pm_btn, use_container_width=True, key=f"pm_fast_{idx_pm}"):
                    _open_food_preview({
                        "dish_name": pm_title,
                        "confidence": "high",
                        "portion_category": "1 porsi standar",
                        "serving_reference": f"1 porsi standar (~{pm_w:.0f}g)",
                        "source_origin": "Standar Lab TKPI Kemenkes RI",
                        "components": [{
                            "name": pm_title,
                            "weight_g": 100.0,
                            "energy_kcal_per_100g": pm_k,
                            "protein_g_per_100g": pm_p,
                            "fat_g_per_100g": pm_f,
                            "carb_g_per_100g": pm_c,
                            "fiber_g_per_100g": pm_fib,
                            "sodium_mg_per_100g": 320.0,
                            "custom_override": True,
                            "source_label": "Standar Lab TKPI Kemenkes RI"
                        }],
                        "health_tip": "Menu populer harian Indonesia. Atur porsi & sesi makan di bawah lalu klik Simpan."
                    }, origin_tab="scanner")
                    st.rerun()

    with subtab_barcode:
        st.markdown("##### 🏷️ **Cek Barcode Kemasan (Lokal + Open Food Facts Live) & Input Manual**")
        st.caption("Ketik nomor barcode kemasan atau klik contoh produk di bawah:")
        
        c_bar1, c_bar2 = st.columns([2.2, 1], vertical_alignment="bottom")
        with c_bar1:
            in_barcode = st.text_input(
                "Nomor Barcode Produk (8–14 Digit):",
                placeholder="Contoh: 8998866200231 (Ultra Milk) / 089686010921 (Indomie)",
                key="input_barcode_field"
            )
        with c_bar2:
            btn_barcode = st.button("🔍 Cek Barcode", type="primary", use_container_width=True, key="btn_check_barcode")

        st.caption("⚡ **Klik Cepat Contoh Produk Kemasan:**")
        sc_b1, sc_b2, sc_b3, sc_b4 = st.columns(4)
        sample_code = None
        if sc_b1.button("🥛 Ultra Milk", use_container_width=True, key="smp_bc1"):
            sample_code = "8998866200231"
        if sc_b2.button("🍜 Indomie", use_container_width=True, key="smp_bc2"):
            sample_code = "089686010921"
        if sc_b3.button("🍫 Nutella", use_container_width=True, key="smp_bc3"):
            sample_code = "3017620422003"
        if sc_b4.button("🍪 Oreo", use_container_width=True, key="smp_bc4"):
            sample_code = "7622210449283"

        target_bc = sample_code or (in_barcode.strip() if btn_barcode else "")
        if target_bc:
            with st.spinner(f"🔍 Mencari barcode `{target_bc}`..."):
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
                    "health_tip": f"Sumber Data: {src_info}. Ukuran saji: {matched.get('serving_unit', '100g')}."
                }, origin_tab="scanner")
                st.toast(f"✅ Produk ditemukan: {matched['food_name']}")
                st.rerun()
            else:
                st.error("Nomor barcode tidak ditemukan. Gunakan fitur **Foto Label Gizi** atau **Input Manual** di bawah ini!")

        with st.expander("📸 **Scan Foto Tabel Informasi Nilai Gizi Kemasan**", expanded=False):
            pkg_file = st.file_uploader("Pilih foto bungkus / label gizi kemasan:", type=["jpg", "jpeg", "png", "webp"], key="scan_pkg_img")
            if pkg_file and api_key:
                im_pkg = Image.open(pkg_file)
                st.image(im_pkg, caption="Foto Kemasan / Label Gizi", width=260)
                if st.button("🔬 Ekstrak Tabel Nilai Gizi Kemasan", type="primary", key="btn_scan_pkg"):
                    with st.spinner("Membaca tabel nilai gizi pada kemasan..."):
                        try:
                            res = analyze_food_image(im_pkg, caption="Kemasan produk ritel / tabel informasi nilai gizi", api_key=api_key)
                            res["source_origin"] = "Ekstraksi Vision Label Gizi"
                            _open_food_preview(res, origin_tab="scanner")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal membaca foto kemasan: {e}")

        with st.expander("➕ **Input Manual Makanan / Resep Sendiri**", expanded=False):
            col_m1, col_m2 = st.columns([1.4, 1], gap="large")
            with col_m1:
                m_food_name = st.text_input("Nama Makanan / Produk:", placeholder="Contoh: Susu Ultra Milk Cokelat 250ml")
                m_serving = st.text_input("Ukuran Porsi:", placeholder="1 kotak (250ml)")
                col_nut1, col_nut2 = st.columns(2)
                with col_nut1:
                    m_kcal = st.number_input("Total Kalori (kkal):", min_value=0.0, value=160.0, step=10.0)
                    m_prot = st.number_input("Protein (gram):", min_value=0.0, value=8.0, step=1.0)
                with col_nut2:
                    m_fat = st.number_input("Lemak (gram):", min_value=0.0, value=4.0, step=1.0)
                    m_carb = st.number_input("Karbohidrat (gram):", min_value=0.0, value=24.0, step=1.0)
                
                MEAL_MAP_MANUAL = {
                    "🌅 Sarapan": "Sarapan",
                    "☀️ Makan Siang": "Makan Siang",
                    "🌙 Makan Malam": "Makan Malam",
                    "🍪 Camilan": "Camilan"
                }
                m_meal_label = st.selectbox("Waktu Makan:", list(MEAL_MAP_MANUAL.keys()), key="sel_manual_time")
                m_meal_clean = MEAL_MAP_MANUAL[m_meal_label]
                
                if st.button("💾 Simpan ke Buku Harian", type="primary", use_container_width=True):
                    if m_food_name.strip():
                        res_log = log_meal(
                            user_id=st.session_state["user"]["user_id"],
                            dish_name=m_food_name.strip(),
                            totals={"energy_kcal": m_kcal, "protein_g": m_prot, "fat_g": m_fat, "carb_g": m_carb, "fiber_g": 0.0, "sodium_mg": 0.0},
                            multiplier=1.0,
                            caption=f"Manual Input ({m_serving})",
                            meal_type=m_meal_clean,
                            log_date=active_diary_date_str,
                            tz_offset=user_tz
                        )
                        st.session_state["last_saved_item"] = res_log
                        add_custom_food(st.session_state["user"]["user_id"], m_food_name.strip(), m_serving, m_kcal, m_prot, m_fat, m_carb)
                        stage_pending_food(
                            food_name=m_food_name.strip(),
                            category="Input Manual Pengguna",
                            kcal_100=m_kcal,
                            p_100=m_prot,
                            f_100=m_fat,
                            c_100=m_carb,
                            serving_unit=m_serving or "1 porsi",
                            source_origin="Input Manual User",
                            submitted_by=current_user["user_id"]
                        )
                        st.success(f"Berhasil dicatat ke sesi {m_meal_clean}!")
                        _mark_db_mutated()
                        st.rerun()
                    else:
                        st.warning("Mohon isi nama makanan terlebih dahulu.")
                        
            with col_m2:
                st.markdown("##### 📚 Koleksi Makanan Tersimpan")
                saved_custom = _fetch_custom_foods_cached(st.session_state["user"]["user_id"], st.session_state.get("db_mutation_ver", 0))
                if saved_custom:
                    for c_item in saved_custom:
                        with st.container(border=True):
                            st.markdown(f"**{c_item['food_name']}** ({c_item['serving_size']})")
                            st.caption(f"🔥 {c_item['energy_kcal']} kkal | P: {c_item['protein_g']}g | L: {c_item['fat_g']}g | K: {c_item['carb_g']}g")
                            col_cbtn1, col_cbtn2 = st.columns([2, 1])
                            with col_cbtn1:
                                if st.button("➕ Catat Lagi", key=f"quick_log_{c_item['id']}", use_container_width=True):
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
                                    st.toast(f"Berhasil mencatat {c_item['food_name']}!")
                                    st.rerun()
                            with col_cbtn2:
                                if st.button("🗑️", key=f"del_c_{c_item['id']}"):
                                    delete_custom_food(c_item["id"], st.session_state["user"]["user_id"])
                                    _mark_db_mutated()
                                    st.rerun()
                else:
                    st.info("Makanan manual yang Anda simpan akan muncul di sini untuk dicatat ulang dengan 1 klik.")

    # KARTU PREVIEW & SIMPAN TUNGGAL ANTI-DOBEL + MINI-REKAP HARI INI
    if st.session_state.get("nutrition_data"):
        if st.session_state.get("preview_origin_tab", "scanner") == "scanner":
            st.markdown("---")
            render_nutrition_preview_card("scanner", current_user, active_diary_date_str, user_tz, is_admin)
        else:
            st.info(f"🍽️ Sedang ada Preview terbuka untuk **{st.session_state['nutrition_data'].get('dish_name')}** di tab lain.")

    st.markdown("---")
    with st.expander(f"📋 **Sudah Masuk Hari Ini ({stats['today_totals']['count']} Menu · {today_kcal:,.1f} kkal)**", expanded=bool(stats["today_meals"])):
        if stats["today_meals"]:
            for mr in stats["today_meals"]:
                mr_c1, mr_c2, mr_c3 = st.columns([3.2, 1.5, 0.6], vertical_alignment="center")
                with mr_c1:
                    st.markdown(f"**[{_normalize_meal_key(mr.get('meal_type'))}] {mr['dish_name']}**")
                with mr_c2:
                    st.caption(f"{mr['energy_kcal']} kkal")
                with mr_c3:
                    if st.button("🗑️", key=f"mini_del_{mr['id']}", help="Hapus dari hari ini"):
                        delete_meal_log(mr["id"], st.session_state["user"]["user_id"])
                        _mark_db_mutated()
                        st.toast("Catatan dihapus.")
                        st.rerun()
        else:
            st.caption("Belum ada makanan yang disimpan pada tanggal ini. Setelah Analisis, klik **💾 Simpan ke Buku Harian**.")

# ================= TAB 3: SUMBER DATA & ENSIKLOPEDIA NUTRISI =================
with tab_sources:
    st.markdown("## 📚 **Pusat Rujukan Pangkalan Data Nutrisi**")
    st.caption("Seluruh kalkulasi nilai nutrisi pada sistem Nutrisi Cerdas berpatokan pada data uji laboratorium ilmiah TKPI Kemenkes RI, USDA, dan Open Food Facts.")

    # 🛡️ PANEL KURASI & EDIT SEBELUM PUBLIKASI (Khusus Admin — Menghindari Update Mendadak)
    if is_admin:
        pending_list = _fetch_pending_foods_cached("pending", st.session_state.get("db_mutation_ver", 0))
        with st.expander(f"🛡️ **Panel Kurasi & Edit Data Gizi Sebelum Publikasi ({len(pending_list)} Draft Menunggu - Admin Only)**", expanded=bool(len(pending_list) > 0)):
            st.caption("Setiap data baru dari **Open Food Facts API**, **AI Auto-Learn**, maupun **Usulan Pengguna** masuk ke ruang tinjauan (Staging) ini terlebih dahulu agar Anda dapat mengedit dan memverifikasi angkanya sebelum resmi dipublikasikan ke database utama.")
            if pending_list:
                for p_item in pending_list[:15]:
                    with st.container(border=True):
                        st.markdown(f"**📝 Draft #{p_item['id']}: {p_item['food_name']}** • `{p_item['source_origin']}`")
                        pc1, pc2, pc3 = st.columns([2, 2, 1.2])
                        with pc1:
                            p_name = st.text_input("Nama Pangan:", value=p_item["food_name"], key=f"pend_n_{p_item['id']}")
                            p_cat = st.text_input("Kategori:", value=p_item["category"] or "Produk Kemasan", key=f"pend_cat_{p_item['id']}")
                            p_bc = st.text_input("Barcode:", value=p_item["barcode"] or "", key=f"pend_bc_{p_item['id']}")
                        with pc2:
                            p_kcal = st.number_input("Energi (kkal/100g):", value=float(p_item["energy_kcal"]), step=5.0, key=f"pend_k_{p_item['id']}")
                            p_prot = st.number_input("Protein (g/100g):", value=float(p_item["protein_g"]), step=0.5, key=f"pend_p_{p_item['id']}")
                            p_fat = st.number_input("Lemak (g/100g):", value=float(p_item["fat_g"]), step=0.5, key=f"pend_f_{p_item['id']}")
                            p_carb = st.number_input("Karbo (g/100g):", value=float(p_item["carb_g"]), step=0.5, key=f"pend_c_{p_item['id']}")
                        with pc3:
                            st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                            if st.button("🚀 Publikasikan", type="primary", use_container_width=True, key=f"btn_pub_{p_item['id']}"):
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
                                st.toast(f"✅ {p_name} resmi dipublikasikan ke katalog utama!")
                                st.rerun()
                            if st.button("🗑️ Tolak Draft", use_container_width=True, key=f"btn_rej_{p_item['id']}"):
                                reject_pending_food(p_item["id"])
                                _mark_db_mutated()
                                st.toast("Draft dihapus dari antrean.")
                                st.rerun()
            else:
                st.success("✨ Tidak ada antrean draft yang menunggu. Anda juga dapat menambahkan atau mengedit data pangan baru melalui formulir di bawah.")

            st.markdown("---")
            st.markdown("##### ➕ **Tambah / Edit Langsung Pangan ke Katalog Utama**")
            add_c1, add_c2, add_c3 = st.columns(3)
            with add_c1:
                new_f_name = st.text_input("Nama Makanan / Produk:", placeholder="Misal: Susu Steril Bear Brand", key="new_cat_name")
                new_f_cat = st.text_input("Kategori:", value="Produk Ritel Terverifikasi", key="new_cat_cat")
                new_f_bc = st.text_input("Kode Barcode (Opsional):", placeholder="8992696404441", key="new_cat_bc")
            with add_c2:
                new_f_kcal = st.number_input("Kalori (per 100g/saji):", min_value=0.0, value=120.0, step=5.0, key="new_cat_kcal")
                new_f_p = st.number_input("Protein (g):", min_value=0.0, value=6.0, step=0.5, key="new_cat_p")
                new_f_f = st.number_input("Lemak (g):", min_value=0.0, value=4.5, step=0.5, key="new_cat_f")
            with add_c3:
                new_f_c = st.number_input("Karbohidrat (g):", min_value=0.0, value=9.5, step=0.5, key="new_cat_c")
                new_f_fib = st.number_input("Serat (g):", min_value=0.0, value=0.0, step=0.5, key="new_cat_fib")
                st.markdown("<div style='height: 26px;'></div>", unsafe_allow_html=True)
                if st.button("💾 Simpan & Publikasikan ke Katalog", type="primary", use_container_width=True, key="btn_direct_pub"):
                    if new_f_name.strip():
                        publish_food_to_catalog(
                            food_name=new_f_name.strip(), category=new_f_cat.strip(),
                            kcal_100=new_f_kcal, p_100=new_f_p, f_100=new_f_f, c_100=new_f_c,
                            fib_100=new_f_fib, barcode=new_f_bc.strip()
                        )
                        _fetch_tkpi_categories_and_count.clear()
                        _search_tkpi_catalog_cached.clear()
                        _mark_db_mutated()
                        st.success(f"✅ '{new_f_name}' berhasil disimpan dan dipublikasikan ke katalog utama!")
                        st.rerun()
                    else:
                        st.warning("Isi nama makanan terlebih dahulu.")

    # 3 Kartu Lembaga Sumber Resmi
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #10b981;">🏛️ Kemenkes RI (TKPI)</h4>
            <p style="font-size: 0.88rem; opacity: 0.82; margin-top: 0.4rem;">
                <strong>Tabel Komposisi Pangan Indonesia</strong> (Panganku.org). Memuat lebih dari 1.100+ bahan mentah & masakan tradisional nusantara per 100g BDD (Bagian Dapat Dimakan).
            </p>
            <a href="https://www.panganku.org" target="_blank" style="font-weight: 700; color: #10b981; font-size: 0.85rem;">Kunjungi Panganku.org ↗</a>
        </div>
        """, unsafe_allow_html=True)
    with col_s2:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #0284c7;">🌐 Open Food Facts & USDA</h4>
            <p style="font-size: 0.88rem; opacity: 0.82; margin-top: 0.4rem;">
                Pangkalan data terbuka produk kemasan dunia (3+ juta barcode EAN-13) dan standar laboratorium Departemen Pertanian AS untuk bahan pangan global.
            </p>
            <a href="https://world.openfoodfacts.org" target="_blank" style="font-weight: 700; color: #0284c7; font-size: 0.85rem;">Kunjungi Open Food Facts ↗</a>
        </div>
        """, unsafe_allow_html=True)
    with col_s3:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #d97706;">🔬 NilaiGizi.com & AKG</h4>
            <p style="font-size: 0.88rem; opacity: 0.82; margin-top: 0.4rem;">
                Platform nutrisionis nasional (AhliGizi.ID) dan acuan Angka Kecukupan Gizi (AKG Permenkes No. 28/2019) untuk validasi porsi rumah tangga (URT) Indonesia.
            </p>
            <a href="https://nilaigizi.com" target="_blank" style="font-weight: 700; color: #d97706; font-size: 0.85rem;">Kunjungi NilaiGizi.com ↗</a>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🔍 **Pencarian Terbuka Pangkalan Data Laboratorium & Ritel**")
    st.caption("Cari bahan makanan atau menu masakan apapun di database lokal untuk melihat profil nutrisi per 100 gram:")

    col_q1, col_q2 = st.columns([2, 1])
    with col_q1:
        search_query = st.text_input("Ketik nama makanan atau nomor barcode:", placeholder="Contoh: ayam, nasi, telur, ultra milk, indomie, fitbar", key="kb_search")
    cats, total_db_count = _fetch_tkpi_categories_and_count()
    with col_q2:
        sel_cat = st.selectbox("Filter Kategori:", ["Semua Kategori"] + cats, key="kb_cat")

    results = _search_tkpi_catalog_cached(search_query.strip(), sel_cat)

    if results:
        table_kb = []
        for r in results:
            table_kb.append({
                "Nama Pangan": r[0],
                "Kategori": r[1] or "-",
                "Energi (kkal/100g)": r[2],
                "Protein (g)": r[3],
                "Lemak (g)": r[4],
                "Karbohidrat (g)": r[5],
                "Serat (g)": r[6],
                "Natrium (mg)": r[7],
                "Barcode": r[8] or "-"
            })
        st.dataframe(table_kb, use_container_width=True, hide_index=True)
        st.caption(f"Menampilkan {len(results)} hasil teratas dari total {total_db_count:,} entri pangan terverifikasi.")

        # Catat Langsung dari Hasil Pencarian Database (0 Kuota AI)
        with st.container(border=True):
            st.markdown("##### ⚡ **Catat Langsung dari Database TKPI (0 Kuota AI)**")
            db_c1, db_c2, db_c3 = st.columns([2.2, 1.0, 1.3], vertical_alignment="bottom")
            with db_c1:
                pick_idx = st.selectbox(
                    "Pilih pangan dari tabel di atas:",
                    range(len(results)),
                    format_func=lambda idx: f"{results[idx][0]} ({results[idx][2]} kkal/100g)",
                    key="db_pick_idx"
                )
            with db_c2:
                pick_grams = st.number_input("Berat (gram):", min_value=5.0, max_value=2000.0, value=100.0, step=10.0, key="db_pick_grams")
            with db_c3:
                if st.button("➕ Preview & Catat", type="primary", use_container_width=True, key="btn_db_to_preview"):
                    chosen = results[pick_idx]
                    _open_food_preview({
                        "dish_name": chosen[0],
                        "confidence": "high",
                        "portion_category": f"{pick_grams:.0f}g dari database TKPI",
                        "serving_reference": f"{pick_grams:.0f} gram (basis data lab per 100g)",
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
                        "health_tip": "Data resmi terverifikasi lab TKPI Kemenkes / Open Food Facts."
                    }, origin_tab="database")
                    st.rerun()
    else:
        st.info("Tidak ada bahan makanan yang cocok dengan kata kunci tersebut. Coba kata kunci lain.")

    if st.session_state.get("nutrition_data") and st.session_state.get("preview_origin_tab") == "database":
        render_nutrition_preview_card("database", current_user, active_diary_date_str, user_tz, is_admin)

# ================= TAB 4: PANDUAN PENGGUNAAN =================
with tab_guide:
    st.markdown(f"""
    <div style="padding: 1rem 0 1.5rem 0;">
        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
            <h2 style="font-size: 1.8rem; font-weight: 800; margin: 0;">📖 Panduan Cepat Penggunaan</h2>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.78rem; font-weight: 800; padding: 0.25rem 0.7rem; border-radius: 999px;">{APP_CREATOR}</span>
        </div>
        <p style="opacity: 0.8; font-size: 1.02rem; margin-top: 0.4rem;">
            Pelajari cara memanfaatkan fitur pencatatan kalori, Piring Cepat 1-Klik, scanner barcode, dan diary gizi harian secara mudah.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_g1, col_g2 = st.columns([1, 1], gap="large")

    with col_g1:
        with st.container(border=True):
            st.markdown("### 1️⃣ **Mulai & Amankan Akun Open Beta**")
            st.markdown("""
            * **Langkah 1:** Klik tombol **'🔑 Masuk / Daftar'** di sudut kanan atas atau pada banner halaman depan.
            * **Langkah 2:** Buat akun gratis dalam 15 detik menggunakan nama panggilan & PIN minimal 4 karakter.
            * **Keuntungan Open Beta:** Nikmati **5x Scan Foto AI/hari** (3x makan berat + 2x camilan), pelacak berat badan, streak harian, dan catatan tersimpan rapi.
            """)

        with st.container(border=True):
            st.markdown("### 2️⃣ **Fokus Kesehatan, Zona Waktu & Tema**")
            st.markdown("""
            * **Target BMR & Fokus Klinis:** Pilih fokus (*Diet Sehat, Ibu Hamil, Kendali Gula DM, atau Kendali Natrium Hipertensi*) agar *Smart Daily Balancer* menyesuaikan saran gizinya.
            * **Zona Waktu Akurat:** Default menggunakan waktu **WITA (UTC+8)** dan dapat disesuaikan ke WIB/WIT di sidebar.
            * **9 Pilihan Tema Kontras Tinggi:** Buka Sidebar menu **'🎨 Pilihan Tema Tampilan'** untuk mengatur tampilan favorit.
            """)

    with col_g2:
        with st.container(border=True):
            st.markdown("### 3️⃣ **3 Cara Mudah Mencatat Makanan**")
            st.markdown("""
            * **Cara A (1-Klik & Preview Cepat):** Sentuh menu *Sering Kamu Makan*, *Menu Populer*, atau ketik langsung di Beranda — semua tampil sebagai **Preview anti-dobel** sebelum disimpan!
            * **Cara B (Foto Piring HP):** Buka tab **📸 Catat**, unggah foto *(5x/hari Open Beta)*; hidangan se-loyang/wadah besar otomatis ditaksir 1 porsi wajar.
            * **Cara C (Teks AI, Barcode, & Database TKPI):** Ketik menu, pindai barcode, atau catat langsung dari **1.301+ pangan tab Database** secara *unlimited*.
            """)

        with st.container(border=True):
            st.markdown("### 4️⃣ **Edit Inline, Nutri-Grade, Berat Badan & Streak**")
            st.markdown("""
            * **Edit 2-Detik & Anti-Dobel:** Salah waktu makan atau ukuran porsi? Klik **`✏️`** di Buku Harian atau ubah di kartu Preview tanpa khawatir menu ter-double.
            * **Pelacak Berat Badan & Streak:** Catat berat badan berkala dan bangun **Streak Harian** agar kebiasaan makan sehat makin konsisten.
            """)

    if is_admin:
        st.markdown("---")
        st.markdown(f"### 🚀 **Riwayat Pembaruan Web (Patch Notes Admin — {APP_CREATOR} {APP_VERSION})**")
        for p in PATCH_NOTES:
            with st.container(border=True):
                st.markdown(f"#### 📌 **{p['version']}** <span style='font-size: 0.85rem; opacity: 0.7; font-weight: 500;'>({p['date']})</span>", unsafe_allow_html=True)
                for hl in p["highlights"]:
                    st.markdown(f"- {hl}")

    st.markdown("---")
    st.markdown("### 💡 **Pertanyaan Umum (FAQ) & Ketentuan Layanan**")
    with st.expander("❓ Dari mana data kalori dan nutrisi ini diambil?"):
        st.write("Data nutrisi kami berbasis Tabel Komposisi Pangan Indonesia (TKPI) resmi Kementerian Kesehatan RI, USDA FoodData Central, Open Food Facts Global Database, dan NilaiGizi.")
    with st.expander("❓ Bagaimana jika hasil estimasi porsi ingin saya sesuaikan?"):
        st.write("Anda dapat menggeser slider ukuran porsi mulai dari ¼ Porsi (0.25x), ½ Porsi (0.5x), ¾ Porsi (0.75x), 1x, 1.5x, hingga 2x Porsi, melepas centang komponen bahan yang tidak dimakan, atau mengedit langsung lewat tombol ✏️ di Buku Harian.")
    with st.expander("⚖️ Disclaimer Medis & Edukasi Gizi"):
        st.write(
            "Nutrisi Cerdas adalah alat bantu edukasi dan pemantauan gizi harian berbasis TKPI Kemenkes RI. "
            "Estimasi porsi foto AI dapat memiliki selisih bergantung pada pencahayaan dan bahan tersembunyi. "
            "Hasil hitungan maupun saran pada aplikasi ini TIDAK menggantikan diagnosis, terapi medis, atau konsultasi langsung dengan dokter maupun ahli gizi klinis."
        )
    with st.expander("🔒 Kebijakan Privasi & Keamanan Data (Open Beta)"):
        st.write(
            "Data akun dilindungi hashing PBKDF2-SHA256 bersalt dan token sesi bertanda tangan HMAC agar diary tidak dapat dibuka sembarang orang lewat tautan URL. "
            "Foto makanan hanya dikirim sesaat untuk analisis visual komponen pangan dan tidak disimpan permanen di server AI. "
            "Anda dapat mengunduh salinan data pribadi (.json) kapan saja melalui menu '📦 Cadangan Data Pribadi' di Sidebar."
        )

# Footer Resmi original by MN
footer_ver_html = f" • Build <code>{APP_VERSION}</code>" if is_admin else " • Open Beta"
st.markdown(f"""
<div style="text-align: center; padding: 2rem 0 1rem 0; margin-top: 2rem; border-top: 1px solid rgba(125, 125, 125, 0.15); font-size: 0.85rem; opacity: 0.75;">
    🥗 <strong>Nutrisi Cerdas</strong> • Kalkulator & Diary Gizi Terverifikasi • Crafted with ❤️ <strong>{APP_CREATOR}</strong> (Muhammad Nabillah){footer_ver_html}
</div>
""", unsafe_allow_html=True)

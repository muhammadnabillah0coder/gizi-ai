"""
Aplikasi Gizi.AI: Desain Konsep A (Clean Apple Healthtech)
Mendukung:
1. Akun Pribadi (Masuk via Akun Google / Username)
2. Cek Nutrisi Foto & Teks (1.194 Data Lab TKPI Kemenkes RI)
3. Rekapan Harian, Mingguan, & Bulanan (Apple Health Activity Ring & Charts)
"""

import streamlit as st
from PIL import Image
import os
import json
import pandas as pd
from datetime import datetime
import urllib.parse

from gemini_extractor import analyze_food_image, analyze_food_text
from nutrition_engine import calculate_dish_nutrition
from db_history import (
    init_user_history_tables, get_or_create_user, log_meal, delete_meal_log, 
    get_user_history_stats, update_calorie_target, update_user_theme, 
    add_custom_food, get_custom_foods, delete_custom_food,
    get_user_scan_status, record_scan_usage, activate_pro_tier
)
from google_auth import get_google_auth_url, exchange_code_for_user

init_user_history_tables()

st.set_page_config(
    page_title="Nutrisi Cerdas - Pahami Pola Makanmu Berbasis TKPI Kemenkes",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Tangani Redirect Google OAuth Callback (?code=...)
auth_code = st.query_params.get("code", "")
if auth_code:
    # Deteksi URL saat ini untuk redirect URI
    redirect_uri = "https://nutrisi-cerdas.streamlit.app"
    user_info, err_details = exchange_code_for_user(auth_code, redirect_uri)
    if not user_info:
        # Coba fallback ke URL lama atau localhost jika masih transisi
        user_info, err_details = exchange_code_for_user(auth_code, "https://gizi-ai-idn.streamlit.app")
        if not user_info:
            user_info, err_details = exchange_code_for_user(auth_code, "http://localhost:8501")
        
    if user_info and user_info.get("email"):
        email = user_info["email"]
        name = user_info.get("name") or email.split("@")[0]
        u = get_or_create_user(email, display_name=name, auth_provider="google")
        st.session_state["user"] = u
        st.query_params.clear()
        st.query_params["u"] = email
        st.query_params["auth"] = "google"
        st.toast(f"Selamat datang, {name}! Akun Google Anda berhasil terhubung.")
        st.rerun()
    else:
        st.error(f"⚠️ Gagal memverifikasi login Google: {err_details}")
        st.caption("Tips: Pastikan Redirect URI di Google Cloud Console persis `https://nutrisi-cerdas.streamlit.app` dan Client ID/Secret sudah ada di Secrets.")

# Inisialisasi Sesi Akun Pengguna Terlebih Dahulu (Agar Akun & Tema Tersimpan Permanen di Browser)
saved_user_param = st.query_params.get("u", "")
saved_auth_param = st.query_params.get("auth", "local")

if "user" not in st.session_state:
    if saved_user_param:
        st.session_state["user"] = get_or_create_user(saved_user_param.strip(), auth_provider=saved_auth_param)
    else:
        st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")
else:
    # Sinkronkan query param agar URL browser selalu menyimpan identitas user
    active_uid = st.session_state["user"]["user_id"]
    active_auth = st.session_state["user"].get("auth_provider", "local")
    if active_uid != "Tamu (Demo)":
        st.query_params["u"] = active_uid
        st.query_params["auth"] = active_auth

if "nutrition_data" not in st.session_state:
    st.session_state["nutrition_data"] = None

# Deteksi Tema Tersimpan Milik Pengguna
current_user = st.session_state["user"]
user_theme = current_user.get("theme_preference") or "System Default"

# Definisi Palet Tema Lengkap & Kontras Tinggi (Font Selalu Terbaca Tajam)
THEME_STYLES = {
    "System Default": """
        /* Ikuti Tema Sistem / Bawaan Browser */
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
            gap: 12px;
            background-color: rgba(125, 125, 125, 0.15);
            padding: 6px;
            border-radius: 18px;
            margin-bottom: 1.5rem;
        }
        button[data-baseweb="tab"] {
            border-radius: 14px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            padding: 0.75rem 1.6rem !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: rgba(125, 125, 125, 0.3) !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1) !important;
        }
    """,
    "Apple Light": """
        .stApp { background-color: #f8fafc; color: #0f172a; }
        .apple-ring-card {
            background: #ffffff;
            border-radius: 24px;
            padding: 1.8rem;
            box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05);
            border: 1px solid #e2e8f0;
            margin-bottom: 1.5rem;
        }
        .macro-pill {
            background: #ffffff;
            border-radius: 20px;
            padding: 1.2rem 1rem;
            border: 1px solid #edf2f7;
            box-shadow: 0 4px 12px rgba(0,0,0,0.03);
            text-align: center;
        }
        .ring-title, .macro-lbl { font-size: 0.8rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
        .ring-val { font-size: 2.3rem; font-weight: 800; color: #0f172a; margin: 0.3rem 0; }
        .macro-num { font-size: 1.6rem; font-weight: 800; color: #0f172a; margin: 0.2rem 0; }
        div[data-baseweb="tab-list"] {
            gap: 12px;
            background-color: #e2e8f0;
            padding: 6px;
            border-radius: 18px;
            margin-bottom: 1.5rem;
        }
        button[data-baseweb="tab"] {
            border-radius: 14px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            padding: 0.75rem 1.6rem !important;
            color: #475569 !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #ffffff !important;
            color: #0f172a !important;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
        }
    """,
    "Cal AI Dark": """
        .stApp { background-color: #090a0f; color: #f8fafc; }
        .apple-ring-card {
            background: #131722;
            border-radius: 24px;
            padding: 1.8rem;
            border: 1px solid #232936;
            margin-bottom: 1.5rem;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .macro-pill {
            background: #131722;
            border-radius: 20px;
            padding: 1.2rem 1rem;
            border: 1px solid #232936;
            text-align: center;
        }
        .ring-title, .macro-lbl { font-size: 0.8rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
        .ring-val { font-size: 2.3rem; font-weight: 800; color: #ffffff; margin: 0.3rem 0; }
        .macro-num { font-size: 1.6rem; font-weight: 800; color: #ffffff; margin: 0.2rem 0; }
        div[data-baseweb="tab-list"] {
            gap: 12px;
            background-color: #1e2538;
            padding: 6px;
            border-radius: 18px;
            margin-bottom: 1.5rem;
        }
        button[data-baseweb="tab"] {
            border-radius: 14px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            padding: 0.75rem 1.6rem !important;
            color: #94a3b8 !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #00f5a0 !important;
            color: #090a0f !important;
            box-shadow: 0 4px 15px rgba(0, 245, 160, 0.3) !important;
        }
    """,
    "Mint Fresh": """
        .stApp { background-color: #f0fdf4; color: #064e3b; }
        .apple-ring-card {
            background: #ffffff;
            border-radius: 24px;
            padding: 1.8rem;
            border: 1px solid #bbf7d0;
            box-shadow: 0 8px 24px rgba(16, 185, 129, 0.08);
            margin-bottom: 1.5rem;
        }
        .macro-pill {
            background: #ffffff;
            border-radius: 20px;
            padding: 1.2rem 1rem;
            border: 1px solid #bbf7d0;
            text-align: center;
        }
        .ring-title, .macro-lbl { font-size: 0.8rem; font-weight: 700; color: #059669; text-transform: uppercase; letter-spacing: 0.05em; }
        .ring-val { font-size: 2.3rem; font-weight: 800; color: #064e3b; margin: 0.3rem 0; }
        .macro-num { font-size: 1.6rem; font-weight: 800; color: #064e3b; margin: 0.2rem 0; }
        div[data-baseweb="tab-list"] {
            gap: 12px;
            background-color: #dcfce7;
            padding: 6px;
            border-radius: 18px;
            margin-bottom: 1.5rem;
        }
        button[data-baseweb="tab"] {
            border-radius: 14px !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            padding: 0.75rem 1.6rem !important;
            color: #065f46 !important;
            background-color: transparent !important;
        }
        button[data-baseweb="tab"][aria-selected="true"] {
            background-color: #10b981 !important;
            color: #ffffff !important;
            box-shadow: 0 4px 12px rgba(16, 185, 129, 0.25) !important;
        }
    """
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

# Sidebar: Akun Pribadi & Target Harian
with st.sidebar:
    st.markdown("### 🍏 **Akun & Profil Gizi**")
    
    current_user = st.session_state["user"]
    is_google = current_user.get("auth_provider") == "google"
    
    # Status Login Card
    if is_google:
        st.success(f"G Terhubung: **{current_user['display_name']}**")
        st.caption(f"Akun Google: `{current_user['user_id']}`")
    else:
        st.info(f"👤 Pengguna Aktif: **{current_user['display_name']}**")

    # Pengaturan Tema Tampilan (Tersimpan Permanen ke Akun Pengguna)
    st.markdown("---")
    st.markdown("### 🎨 **Pilihan Tema Tampilan (UI)**")
    theme_options = ["System Default", "Apple Light", "Cal AI Dark", "Mint Fresh"]
    current_idx = theme_options.index(user_theme) if user_theme in theme_options else 0
    selected_theme = st.selectbox("Pilih Gaya Tampilan:", theme_options, index=current_idx)
    if selected_theme != user_theme:
        update_user_theme(current_user["user_id"], selected_theme)
        st.session_state["user"]["theme_preference"] = selected_theme
        st.toast(f"Tema diubah ke {selected_theme}!")
        st.rerun()

    # Target Kalori Harian & Kalkulator BMR/TDEE Otomatis
    st.markdown("---")
    st.markdown("### 🎯 **Target Kalori Harian**")
    current_target = float(current_user.get("daily_calorie_target") or 2000.0)
    new_target = st.number_input("Target Kalori (kkal):", min_value=1000, max_value=4000, value=int(current_target), step=50)
    if new_target != current_target:
        update_calorie_target(current_user["user_id"], float(new_target))
        st.session_state["user"]["daily_calorie_target"] = float(new_target)
        st.toast("Target kalori diperbarui!")
        
    with st.expander("🧮 Hitung Target Ideal (BMR/TDEE)"):
        st.caption("Hitung target kalori berdasarkan rumus standar Mifflin-St Jeor / Kemenkes RI:")
        gender = st.radio("Jenis Kelamin:", ["Pria", "Wanita"], horizontal=True)
        bb = st.number_input("Berat Badan (kg):", value=65.0, step=1.0)
        tb = st.number_input("Tinggi Badan (cm):", value=170.0, step=1.0)
        usia = st.number_input("Usia (tahun):", value=25, step=1)
        aktivitas = st.selectbox("Aktivitas Harian:", [
            "Sedentari (Jarang olahraga / di depan laptop)",
            "Ringan (Olahraga 1-3 hari/minggu)",
            "Sedang (Olahraga 3-5 hari/minggu)",
            "Sangat Aktif (Latihan intensif setiap hari)"
        ])
        tujuan = st.selectbox("Tujuan Program:", [
            "Turunkan Berat Badan (Defisit 400 kkal)",
            "Jaga Berat Badan Ideal (Maintenance)",
            "Tambah Berat / Massa Otot (Surplus 400 kkal)"
        ])
        
        if st.button("Hitung & Terapkan Target", use_container_width=True):
            # Formula Mifflin - St Jeor
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
            st.success(f"🎯 Target kalori berhasil diatur menjadi **{recom_target} kkal/hari**!")
            st.rerun()

# Header Brand Utama dengan Logo Menonjol & Kotak Login Akun Langsung di Halaman Utama
current_user = st.session_state["user"]
is_google = current_user.get("auth_provider") == "google"
scan_status = get_user_scan_status(current_user["user_id"])

col_head1, col_head2 = st.columns([2, 1.2], vertical_alignment="center")

with col_head1:
    st.markdown("""
    <div style="display: flex; align-items: center; gap: 18px; margin-bottom: 0.5rem; padding: 0.5rem 0;">
        <div style="
            font-size: 3.5rem;
            background: linear-gradient(135deg, #10b981 0%, #059669 100%);
            width: 82px;
            height: 82px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 24px;
            box-shadow: 0 10px 25px -4px rgba(16, 185, 129, 0.4);
        ">🥗</div>
        <div>
            <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <h1 style="font-size: 2.6rem; font-weight: 800; margin: 0; letter-spacing: -0.02em;">Nutrisi Cerdas</h1>
                <span style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-size: 0.8rem; font-weight: 800; padding: 0.35rem 0.8rem; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid rgba(16, 185, 129, 0.3);">
                    DATA RESMI TKPI KEMENKES
                </span>
            </div>
            <p style="margin: 0.2rem 0 0 0; opacity: 0.8; font-size: 1.05rem; font-weight: 500;">
                Kalkulator & Diary Nutrisi: Pahami Pola Makanmu Berbasis Data Uji Lab Pangan
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_head2:
    with st.container(border=True):
        from db_history import is_admin_user
        is_admin = is_admin_user(current_user["user_id"])
        
        if is_admin:
            tier_badge = "👑 FOUNDER / ADMIN (Lifetime Unlimited)"
        elif scan_status["is_pro"]:
            tier_badge = "👑 PRO (Unlimited)"
        else:
            tier_badge = f"🌱 Free ({scan_status['scans_today']}/3 Scan Hari Ini)"
            
        st.markdown(f"👤 **{current_user['display_name']}** • `{tier_badge}`")
        
        c_acc1, c_acc2 = st.columns([1, 1])
        with c_acc1:
            with st.popover("🔑 Masuk Akun", use_container_width=True):
                st.markdown("##### 🌐 Masuk Otomatis Google")
                # URL OAuth resmi Google (disesuaikan dengan domain baru nutrisi-cerdas)
                oauth_redirect = "https://nutrisi-cerdas.streamlit.app"
                google_auth_url = get_google_auth_url(oauth_redirect)
                
                st.markdown(f"""
                <a href="{google_auth_url}" target="_self" style="text-decoration: none;">
                    <div style="
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        gap: 10px;
                        background-color: #ffffff;
                        color: #1f2937;
                        border: 1px solid #d1d5db;
                        border-radius: 12px;
                        padding: 0.6rem 1rem;
                        font-weight: 700;
                        font-size: 0.95rem;
                        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
                        cursor: pointer;
                        margin-bottom: 0.8rem;
                    ">
                        <img src="https://www.gstatic.com/images/branding/product/1x/gsa_512dp.png" width="22" height="22" alt="Google">
                        Sign in with Google
                    </div>
                </a>
                """, unsafe_allow_html=True)
                
                st.markdown("---")
                st.caption("Atau masukkan email / nama secara manual:")
                in_email = st.text_input("Email Google / Username:", placeholder="nama@gmail.com", key="pop_email")
                if st.button("Simpan & Masuk Manual", type="secondary", use_container_width=True, key="pop_btn"):
                    if "@" in in_email:
                        u = get_or_create_user(in_email.strip(), auth_provider="google")
                        st.session_state["user"] = u
                        st.query_params["u"] = u["user_id"]
                        st.query_params["auth"] = "google"
                        st.rerun()
                    elif in_email.strip():
                        u = get_or_create_user(in_email.strip(), auth_provider="local")
                        st.session_state["user"] = u
                        st.query_params["u"] = u["user_id"]
                        st.query_params["auth"] = "local"
                        st.rerun()
                st.caption("Data makanan harian Anda tersimpan permanen dan terikat pada profil ini.")
        
        with c_acc2:
            with st.popover("⚡ Upgrade / Status PRO", use_container_width=True):
                st.markdown("### 👑 **Nutrisi Cerdas PRO**")
                
                if scan_status["is_pro"]:
                    if is_admin:
                        st.success("🌟 **Status: FOUNDER / ADMIN (Seumur Hidup)**")
                        st.caption("Akses semua fitur tanpa batas kuota selamanya.")
                    else:
                        st.success(f"🎉 **Status: PRO Aktif** (Sisa ~{scan_status['days_left']} hari)")
                        st.caption("Scan foto makanan tanpa batas dan riwayat lengkap aktif.")
                else:
                    st.markdown("""
                    **Cuma Rp 19.000 / bulan** *(Jauh lebih hemat dari kompetitor!)*
                    - 🚀 **Scan Foto Makanan Sepuasnya (Unlimited)**
                    - 🤖 **Auto-Learning AI Prioritas**
                    - 📊 **Export Laporan Gizi Lengkap**
                    """)
                    st.info("🎁 **Spesial Peluncuran:** Coba gratis 30 Hari penuh!")
                    if st.button("✨ Klaim Uji Coba Gratis 1 Bulan PRO", type="primary", use_container_width=True):
                        activate_pro_tier(current_user["user_id"], days=30)
                        st.toast("Selamat! Uji Coba Gratis 1 Bulan PRO Anda sudah aktif!")
                        st.rerun()
                    st.caption("💳 Nanti setelah 30 hari, perpanjangan sangat murah: Rp 19rb via QRIS/GoPay/BCA.")

# Navigasi Menu Atas (Clean Tabs dengan Ikon Jelas)
tab_diary, tab_scanner, tab_sources, tab_guide = st.tabs([
    "📊  DASHBOARD REKAPAN (HARI / MINGGU / BULAN)",
    "📸  CATAT MAKANAN BARU (FOTO & TEKS)",
    "📚  SUMBER DATA & ENSIKLOPEDIA GIZI",
    "📖  PANDUAN PENGGUNAAN"
])

# Ambil statistik riwayat akun
stats = get_user_history_stats(st.session_state["user"]["user_id"])
target_kcal = float(st.session_state["user"].get("daily_calorie_target") or 2000.0)
today_kcal = stats["today_totals"]["energy_kcal"]
pct_today = min(round((today_kcal / target_kcal) * 100, 1), 100.0) if target_kcal > 0 else 0

# ================= TAB 1: DASHBOARD REKAPAN KALORI =================
with tab_diary:
    # Banner Cincin Aktivitas Kalori Hari Ini (Apple Health Style)
    st.markdown(f"""
    <div class="apple-ring-card">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <div class="ring-title">🎯 Cincin Kalori Hari Ini ({datetime.now().strftime('%d %B %Y')})</div>
                <div class="ring-val">{today_kcal:,.1f} <span style="font-size: 1.1rem; color: #64748b; font-weight: 500;">/ {target_kcal:,.0f} kkal</span></div>
                <div class="ring-sub">Tercapai <strong>{pct_today}%</strong> • Sisa budget: <strong>{max(0.0, target_kcal - today_kcal):,.1f} kkal</strong></div>
            </div>
            <div style="text-align: right; margin-top: 0.5rem;">
                <span style="background: rgba(16, 185, 129, 0.15); color: #059669; padding: 0.4rem 1rem; border-radius: 9999px; font-weight: 700; font-size: 0.88rem;">
                    {stats['today_totals']['count']} Menu Tercatat
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Progress Bar Lembut
    st.progress(pct_today / 100.0)

    # 4 Makronutrien Hari Ini
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #0284c7;">{stats['today_totals']['protein_g']}g</div>
            <div class="macro-lbl">Protein Hari Ini</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #d97706;">{stats['today_totals']['fat_g']}g</div>
            <div class="macro-lbl">Lemak Hari Ini</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m3:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #059669;">{stats['today_totals']['carb_g']}g</div>
            <div class="macro-lbl">Karbohidrat</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m4:
        st.markdown(f"""
        <div class="macro-pill">
            <div class="macro-num" style="color: #7c3aed;">{stats['today_totals']['fiber_g']}g</div>
            <div class="macro-lbl">Serat</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    
    # Pembagian 2 Kolom: Mingguan & Bulanan
    col_week, col_month = st.columns([1.5, 1], gap="large")
    
    with col_week:
        st.markdown("### 📊 **Tren 7 Hari Terakhir (Mingguan)**")
        if stats["weekly_data"]:
            df_week = pd.DataFrame(stats["weekly_data"])
            df_week["day"] = pd.to_datetime(df_week["day"]).dt.strftime("%a (%d/%m)")
            st.bar_chart(df_week.set_index("day")["total_kcal"], color="#10b981")
        else:
            st.info("Belum ada catatan makan dalam 7 hari terakhir. Mulai catat di tab sebelah!")

    with col_month:
        st.markdown("### 🗓️ **Rekapan 30 Hari (Bulanan)**")
        m_data = stats["monthly_summary"]
        st.markdown(f"""
        <div class="apple-ring-card">
            <div class="ring-title">Total Kalori 30 Hari</div>
            <div class="ring-val" style="color: #0284c7;">{m_data['total_kcal']:,.0f} <span style="font-size: 1rem; color: #64748b; font-weight: 500;">kkal</span></div>
            <hr style="margin: 0.8rem 0; border: none; border-top: 1px solid #f1f5f9;">
            <p style="margin: 0.3rem 0; color: #475569;">📅 <strong>Hari Aktif Mencatat:</strong> {m_data['active_days']} hari</p>
            <p style="margin: 0.3rem 0; color: #475569;">🍽️ <strong>Total Menu Masuk:</strong> {m_data['total_meals']} porsi</p>
            <p style="margin: 0.3rem 0; color: #475569;">⚡ <strong>Rata-rata Harian:</strong> {(m_data['total_kcal'] / max(1, m_data['active_days'])):,.0f} kkal/hari</p>
        </div>
        """, unsafe_allow_html=True)

    # Riwayat Makan Hari Ini & Tombol Hapus Baris
    st.markdown("### 📝 **Buku Harian Makan Hari Ini**")
    
    # Tombol Bagikan ke WhatsApp & Ekspor
    if stats["today_meals"]:
        wa_text = (
            f"🥗 *Laporan Gizi Harian Saya ({datetime.now().strftime('%d %B %Y')})*\n"
            f"👤 Akun: {current_user['display_name']}\n"
            f"🔥 *Total Kalori:* {today_kcal} / {target_kcal:.0f} kkal ({pct_today}%)\n"
            f"🥩 Protein: {stats['today_totals']['protein_g']}g | 🥑 Lemak: {stats['today_totals']['fat_g']}g | 🍚 Karbo: {stats['today_totals']['carb_g']}g\n\n"
            f"📋 *Menu Hari Ini:*\n"
        )
        for idx, m in enumerate(stats["today_meals"], 1):
            m_type = m.get("meal_type") or "Makan"
            wa_text += f"{idx}. [{m_type}] {m['dish_name']} ({m['energy_kcal']} kkal)\n"
        wa_text += "\nCek & hitung nutrisi makananmu di: https://gizi-ai-idn.streamlit.app"
        
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
                cols_to_export = [c for c in ["logged_at", "meal_type", "dish_name", "energy_kcal", "protein_g", "fat_g", "carb_g", "fiber_g", "photo_caption"] if c in df_export.columns]
                csv_data = df_export[cols_to_export].to_csv(index=False).encode('utf-8')
                st.download_button("📥 Unduh Rekap (CSV/Excel)", data=csv_data, file_name=f"gizi_harian_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

        st.markdown("<br>", unsafe_allow_html=True)

        # Kelompokkan per Waktu Makan
        grouped_meals = {}
        for m in stats["today_meals"]:
            mtype = m.get("meal_type") or "Lainnya"
            if mtype not in grouped_meals:
                grouped_meals[mtype] = []
            grouped_meals[mtype].append(m)

        for mtype, meals_in_group in grouped_meals.items():
            subtotal_kcal = sum(x["energy_kcal"] for x in meals_in_group)
            st.markdown(f"##### {mtype} <span style='font-size: 0.88rem; color: #10b981; font-weight: 700;'>({subtotal_kcal:,.1f} kkal)</span>", unsafe_allow_html=True)
            
            for m in meals_in_group:
                time_str = datetime.strptime(m["logged_at"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M") if " " in m["logged_at"] else m["logged_at"]
                col_row1, col_row2, col_row3 = st.columns([3, 2, 1], vertical_alignment="center")
                with col_row1:
                    st.markdown(f"**{m['dish_name']}**")
                    sub_cap = f"_{m['photo_caption']}_" if m['photo_caption'] else ""
                    st.caption(f"🕒 {time_str} {sub_cap}")
                with col_row2:
                    st.markdown(f"**{m['energy_kcal']} kkal** | P: {m['protein_g']}g | L: {m['fat_g']}g | K: {m['carb_g']}g")
                with col_row3:
                    if st.button("🗑️ Hapus", key=f"del_{m['id']}", use_container_width=True):
                        delete_meal_log(m["id"], st.session_state["user"]["user_id"])
                        st.toast("Catatan makanan berhasil dihapus.")
                        st.rerun()
                st.divider()
    else:
        st.caption("Belum ada makanan yang dicatat hari ini.")

# ================= TAB 2: CATAT MAKANAN BARU =================
with tab_scanner:
    # Ambil API key otomatis
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]

    subtab_foto, subtab_kamera, subtab_teks, subtab_manual = st.tabs([
        "📁 Unggah Foto Galeri", 
        "📸 Jepret Kamera HP", 
        "✍️ Tulis Menu Harian", 
        "➕ Input Manual Sendiri"
    ])
    
    with subtab_foto:
        c_up1, c_up2 = st.columns([1, 1], gap="large")
        with c_up1:
            up_file = st.file_uploader("Pilih foto makanan:", type=["jpg", "jpeg", "png", "webp"], key="scan_foto")
            if up_file:
                im = Image.open(up_file)
                st.image(im, caption="Foto Makanan", use_container_width=True)
                p_caption = st.text_input("💬 Catatan / Keterangan (Opsional):", placeholder="Contoh: Bumbu kacang dipisah / ayam tanpa kulit", key="f_cap")
            else:
                p_caption = ""
        with c_up2:
            if up_file:
                st.markdown("#### Siap Menganalisis?")
                st.caption("AI memindai porsi URT & mencocokkan ke 1.194 data laboratorium resmi Kemenkes.")
                
                if not scan_status["can_scan"]:
                    st.warning("⚠️ **Batas Scan Harian Free Tercapai (3/3).**")
                    st.markdown("Nikmati **Scan Foto Sepuasnya** cuma **Rp 19.000/bulan**!")
                    if st.button("👑 Buka Scan Unlimited (Uji Coba PRO)", type="primary", use_container_width=True, key="btn_up_pro1"):
                        activate_pro_tier(current_user["user_id"], days=30)
                        st.toast("Akun PRO aktif! Silakan scan kembali.")
                        st.rerun()
                else:
                    if st.button("🚀 Analisis Gizi Foto", type="primary", use_container_width=True, key="btn_foto"):
                        with st.spinner("Menganalisis visual foto makanan..."):
                            try:
                                res = analyze_food_image(im, caption=p_caption, api_key=api_key)
                                res["user_caption"] = p_caption
                                record_scan_usage(current_user["user_id"])
                                st.session_state["nutrition_data"] = res
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal memproses gambar: {e}")
            else:
                st.info("💡 **Tips:** Foto piring makan dari atas agar semua lauk dan sayuran tampak jelas.")

    with subtab_kamera:
        c_cam1, c_cam2 = st.columns([1, 1], gap="large")
        with c_cam1:
            cam_file = st.camera_input("Arahkan kamera ke piring makanan:")
            if cam_file:
                im_cam = Image.open(cam_file)
                cam_caption = st.text_input("💬 Catatan / Keterangan (Opsional):", placeholder="Contoh: Tanpa santan / porsi setengah", key="c_cap")
            else:
                cam_caption = ""
        with c_cam2:
            if cam_file:
                st.markdown("#### Foto Terambil!")
                st.caption("Klik tombol di bawah untuk langsung menghitung gizi dan kalori foto jepretan Anda.")
                
                if not scan_status["can_scan"]:
                    st.warning("⚠️ **Batas Scan Harian Free Tercapai (3/3).**")
                    st.markdown("Nikmati **Scan Foto Sepuasnya** cuma **Rp 19.000/bulan**!")
                    if st.button("👑 Buka Scan Unlimited (Uji Coba PRO)", type="primary", use_container_width=True, key="btn_up_pro2"):
                        activate_pro_tier(current_user["user_id"], days=30)
                        st.toast("Akun PRO aktif! Silakan scan kembali.")
                        st.rerun()
                else:
                    if st.button("🚀 Analisis Jepretan Kamera", type="primary", use_container_width=True, key="btn_cam"):
                        with st.spinner("Menganalisis foto kamera..."):
                            try:
                                res = analyze_food_image(im_cam, caption=cam_caption, api_key=api_key)
                                res["user_caption"] = cam_caption
                                record_scan_usage(current_user["user_id"])
                                st.session_state["nutrition_data"] = res
                                st.rerun()
                            except Exception as e:
                                st.error(f"Gagal memproses gambar kamera: {e}")
            else:
                st.info("📷 **Kamera Langsung:** Fitur ini membuka kamera HP Anda seketika tanpa perlu menyimpan foto ke galeri.")

    with subtab_teks:
        t_input = st.text_area("Tuliskan menu makanan:", placeholder="Contoh: 1 piring gado-gado lontong pakai telur rebus dan bumbu kacang", height=100)
        if st.button("Hitung Gizi Menu", type="primary", use_container_width=True, key="btn_teks"):
            if not api_key:
                st.error("⚠️ API Key belum terkonfigurasi. Silakan periksa pengaturan di sidebar atau secrets.")
            elif not t_input.strip():
                st.warning("Silakan tulis menu makanan terlebih dahulu.")
            else:
                with st.spinner("Menghitung nilai gizi dari database lab..."):
                    try:
                        res = analyze_food_text(t_input, api_key=api_key)
                        res["user_caption"] = t_input
                        st.session_state["nutrition_data"] = res
                        st.toast("✅ Analisis berhasil! Gulir ke bawah untuk melihat hasil.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal memproses teks: {e}")

    with subtab_manual:
        st.markdown("#### ➕ Catat Makanan / Produk Kemasan Sendiri")
        st.caption("Masukkan informasi dari label gizi kemasan (misal: susu, roti, suplemen) atau resep khusus buatanmu.")
        
        col_m1, col_m2 = st.columns([1.5, 1], gap="large")
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
            
            m_meal_time = st.selectbox("Waktu Makan:", ["🌅 Sarapan", "☀️ Makan Siang", "🌙 Makan Malam", "🥪 Camilan"], key="sel_manual_time")
            
            if st.button("💾 Simpan Langsung ke Diary Hari Ini", type="primary", use_container_width=True):
                if m_food_name.strip():
                    log_meal(
                        user_id=st.session_state["user"]["user_id"],
                        dish_name=m_food_name.strip(),
                        totals={"energy_kcal": m_kcal, "protein_g": m_prot, "fat_g": m_fat, "carb_g": m_carb, "fiber_g": 0.0},
                        multiplier=1.0,
                        caption=f"Manual Input ({m_serving})",
                        meal_type=m_meal_time
                    )
                    # Simpan juga ke katalog pribadi user
                    add_custom_food(st.session_state["user"]["user_id"], m_food_name.strip(), m_serving, m_kcal, m_prot, m_fat, m_carb)
                    st.success(f"Berhasil dicatat ke sesi {m_meal_time}!")
                    st.rerun()
                else:
                    st.warning("Mohon isi nama makanan terlebih dahulu.")
                    
        with col_m2:
            st.markdown("##### 📚 Koleksi Makanan Manual Tersimpan")
            saved_custom = get_custom_foods(st.session_state["user"]["user_id"])
            if saved_custom:
                for c_item in saved_custom:
                    with st.container(border=True):
                        st.markdown(f"**{c_item['food_name']}** ({c_item['serving_size']})")
                        st.caption(f"🔥 {c_item['energy_kcal']} kkal | P: {c_item['protein_g']}g | L: {c_item['fat_g']}g | K: {c_item['carb_g']}g")
                        col_cbtn1, col_cbtn2 = st.columns([2, 1])
                        with col_cbtn1:
                            if st.button("➕ Catat Lagi", key=f"quick_log_{c_item['id']}", use_container_width=True):
                                log_meal(
                                    user_id=st.session_state["user"]["user_id"],
                                    dish_name=c_item["food_name"],
                                    totals={"energy_kcal": c_item["energy_kcal"], "protein_g": c_item["protein_g"], "fat_g": c_item["fat_g"], "carb_g": c_item["carb_g"], "fiber_g": 0.0},
                                    multiplier=1.0,
                                    caption="Koleksi Pribadi",
                                    meal_type=m_meal_time
                                )
                                st.toast(f"Berhasil mencatat {c_item['food_name']}!")
                                st.rerun()
                        with col_cbtn2:
                            if st.button("🗑️", key=f"del_c_{c_item['id']}"):
                                delete_custom_food(c_item["id"], st.session_state["user"]["user_id"])
                                st.rerun()
            else:
                st.info("Belum ada makanan kustom tersimpan. Makanan yang Anda tambahkan di sebelah kiri akan tersimpan di sini agar bisa dicatat cepat kapan saja tanpa mengetik ulang.")

    # HASIL ANALISIS MAKANAN & TOMBOL SIMPAN
    if st.session_state["nutrition_data"]:
        data = st.session_state["nutrition_data"]
        st.markdown("---")
        
        st.markdown(f"## 🍽️ **{data.get('dish_name', 'Menu Makanan')}**")
        
        # Slider Porsi Interaktif
        st.markdown("##### ⚖️ Sesuaikan Porsi:")
        p_mult = st.select_slider(
            "Porsi:",
            options=[0.7, 1.0, 1.3, 1.5],
            value=1.0,
            format_func=lambda x: {
                0.7: "Porsi Sedikit (~0.7x)",
                1.0: "Porsi Normal (1.0x)",
                1.3: "Porsi Agak Banyak (1.3x)",
                1.5: "Porsi Jumbo (1.5x)"
            }[x],
            label_visibility="collapsed"
        )
        
        calc_res = calculate_dish_nutrition(data.get("components", []), portion_multiplier=p_mult)
        t_tot = calc_res["totals"]
        
        if data.get("health_tip"):
            st.markdown(f"""
            <div class="apple-tip">
                💡 <strong>Saran Gizi:</strong> {data['health_tip']}
            </div>
            """, unsafe_allow_html=True)
            
        # Kartu Makro
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='macro-pill'><div class='macro-num'>{t_tot['energy_kcal']}</div><div class='macro-lbl'>Kalori (kkal)</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#0284c7;'>{t_tot['protein_g']}g</div><div class='macro-lbl'>Protein</div></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#d97706;'>{t_tot['fat_g']}g</div><div class='macro-lbl'>Lemak</div></div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='macro-pill'><div class='macro-num' style='color:#059669;'>{t_tot['carb_g']}g</div><div class='macro-lbl'>Karbohidrat</div></div>", unsafe_allow_html=True)
        
        # Tabel Rincian Bahan Terdeteksi
        st.markdown("##### 📋 Rincian Komposisi Bahan & Standar Lab")
        table_rows = []
        for it in calc_res["items"]:
            table_rows.append({
                "Bahan": it["input_name"],
                "Referensi Lab": it["tkpi_matched_name"],
                "Berat": f"{it['weight_g']} g",
                "Kalori": f"{it['energy_kcal']} kkal",
                "Protein": f"{it['protein_g']} g",
                "Lemak": f"{it['fat_g']} g",
                "Karbo": f"{it['carb_g']} g"
            })
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        # Pilihan Kategori Waktu Makan
        st.markdown("##### 🕒 Waktu Makan:")
        sel_meal_type = st.radio(
            "Kategori:",
            ["🌅 Sarapan", "☀️ Makan Siang", "🌙 Makan Malam", "🥪 Camilan"],
            horizontal=True,
            index=1,
            label_visibility="collapsed"
        )
        
        # Tombol Simpan ke Akun Pribadi & Tombol Batal
        col_act1, col_act2 = st.columns([3, 1])
        with col_act1:
            if st.button(f"💾 Simpan ke Buku Harian ({st.session_state['user']['display_name']})", type="primary", use_container_width=True):
                log_meal(
                    user_id=st.session_state["user"]["user_id"],
                    dish_name=data.get("dish_name", "Menu Sehat"),
                    totals=t_tot,
                    multiplier=p_mult,
                    caption=data.get("user_caption", ""),
                    meal_type=sel_meal_type
                )
                st.success(f"Berhasil dicatat ke sesi {sel_meal_type} akun {st.session_state['user']['display_name']}! Silakan cek tab Dashboard.")
                st.session_state["nutrition_data"] = None
                st.rerun()
        with col_act2:
            if st.button("❌ Batal / Bersihkan", use_container_width=True):
                st.session_state["nutrition_data"] = None
                st.rerun()

# ================= TAB 3: SUMBER DATA & ENSIKLOPEDIA GIZI =================
with tab_sources:
    st.markdown("## 📚 **Pusat Rujukan & Sumber Data Nutrisi Resmi**")
    st.caption("Seluruh kalkulasi nilai gizi pada sistem Gizi.AI berpatokan 100% pada data uji laboratorium ilmiah dan resmi pemerintah, bukan estimasi fiksi.")

    # 3 Kartu Lembaga Sumber Resmi
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #10b981;">🏛️ Kemenkes RI (TKPI)</h4>
            <p style="font-size: 0.88rem; color: #64748b; margin-top: 0.4rem;">
                <strong>Tabel Komposisi Pangan Indonesia</strong> (Panganku.org). Memuat lebih dari 1.100+ bahan mentah & masakan tradisional nusantara per 100g BDD (Bagian Dapat Dimakan).
            </p>
            <a href="https://www.panganku.org" target="_blank" style="font-weight: 700; color: #10b981; font-size: 0.85rem;">Kunjungi Panganku.org ↗</a>
        </div>
        """, unsafe_allow_html=True)
    with col_s2:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #0284c7;">🌾 USDA FoodData Central</h4>
            <p style="font-size: 0.88rem; color: #64748b; margin-top: 0.4rem;">
                Standar laboratorium internasional Departemen Pertanian Amerika Serikat untuk bahan baku global, aneka jenis kopi, buah impor, dan menu modern terverifikasi.
            </p>
            <a href="https://fdc.nal.usda.gov" target="_blank" style="font-weight: 700; color: #0284c7; font-size: 0.85rem;">Kunjungi USDA FoodData ↗</a>
        </div>
        """, unsafe_allow_html=True)
    with col_s3:
        st.markdown("""
        <div class="apple-ring-card">
            <h4 style="margin: 0; color: #d97706;">🔬 NilaiGizi.com & AKG</h4>
            <p style="font-size: 0.88rem; color: #64748b; margin-top: 0.4rem;">
                Platform nutrisionis nasional (AhliGizi.ID) dan acuan Angka Kecukupan Gizi (AKG Permenkes No. 28/2019) untuk validasi porsi rumah tangga (URT) Indonesia.
            </p>
            <a href="https://nilaigizi.com" target="_blank" style="font-weight: 700; color: #d97706; font-size: 0.85rem;">Kunjungi NilaiGizi.com ↗</a>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🔍 **Pencarian Terbuka Pangkalan Data Laboratorium (1.271 Item)**")
    st.caption("Cari bahan makanan atau menu masakan apapun di database lokal untuk melihat profil gizi per 100 gram:")

    col_q1, col_q2 = st.columns([2, 1])
    with col_q1:
        search_query = st.text_input("Ketik nama makanan:", placeholder="Contoh: ayam, nasi, telur, tempe, kopi, kangkung", key="kb_search")
    with col_q2:
        # Ambil daftar kategori unik
        import sqlite3
        conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cats = [r[0] for r in cur.execute("SELECT DISTINCT category FROM food_composition WHERE category IS NOT NULL ORDER BY category").fetchall()]
        sel_cat = st.selectbox("Filter Kategori:", ["Semua Kategori"] + cats, key="kb_cat")
        conn.close()

    # Query database
    conn = sqlite3.connect(os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db"))
    cur = conn.cursor()
    sql = "SELECT food_name, category, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg FROM food_composition WHERE 1=1"
    params = []
    if search_query.strip():
        sql += " AND food_name LIKE ?"
        params.append(f"%{search_query.strip()}%")
    if sel_cat != "Semua Kategori":
        sql += " AND category = ?"
        params.append(sel_cat)
    sql += " ORDER BY food_name ASC LIMIT 50"

    results = cur.execute(sql, params).fetchall()
    conn.close()

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
                "Natrium (mg)": r[7]
            })
        st.dataframe(table_kb, use_container_width=True, hide_index=True)
        st.caption(f"Menampilkan {len(results)} hasil teratas dari total 1.271 entri laboratorium.")
    else:
        st.info("Tidak ada bahan makanan yang cocok dengan kata kunci tersebut. Coba kata kunci lain.")

# ================= TAB 4: PANDUAN PENGGUNAAN STEP BY STEP =================
with tab_guide:
    st.markdown("""
    <div style="padding: 1rem 0 1.5rem 0;">
        <h2 style="font-size: 1.8rem; font-weight: 800; margin: 0 0 0.5rem 0;">📖 Panduan Lengkap Penggunaan Nutrisi Cerdas</h2>
        <p style="opacity: 0.8; font-size: 1.05rem;">
            Pelajari cara memanfaatkan fitur pencatatan kalori, kalkulator defisit/surplus, dan diary gizi harian secara maksimal.
        </p>
    </div>
    """, unsafe_allow_html=True)

    col_g1, col_g2 = st.columns([1, 1], gap="large")

    with col_g1:
        with st.container(border=True):
            st.markdown("### 1️⃣ **Mulai & Amankan Akun Anda**")
            st.markdown("""
            * **Langkah 1:** Klik tombol **'🔑 Masuk Akun'** di sudut kanan atas.
            * **Langkah 2:** Klik tombol putih **'Sign in with Google'** untuk menghubungkan akun Gmail Anda, atau ketik nama Anda.
            * **Keuntungan:** Semua riwayat makan, grafik mingguan, dan target kalori Anda akan tersimpan permanen dan tidak akan hilang saat browser ditutup.
            """)

        with st.container(border=True):
            st.markdown("### 2️⃣ **Atur Target Kalori Harian (BMR/TDEE)**")
            st.markdown("""
            * **Langkah 1:** Buka panel samping (Sidebar) di sebelah kiri layar HP/Laptop.
            * **Langkah 2:** Buka menu **'🧮 Hitung Target Ideal (BMR/TDEE)'**.
            * **Langkah 3:** Masukkan berat badan, tinggi badan, usia, dan tujuan program Anda (Turunkan Berat Badan / Jaga Berat Badan / Naikkan Massa Otot).
            * **Langkah 4:** Klik **'Gunakan Target Ini'**, maka Cincin Kalori di Dashboard akan otomatis menyesuaikan!
            """)

    with col_g2:
        with st.container(border=True):
            st.markdown("### 3️⃣ **Mencatat Makanan Harian (3 Cara Mudah)**")
            st.markdown("""
            Masuk ke tab **'📸 CATAT MAKANAN BARU'**:
            * **Cara A (Jepret Kamera HP):** Arahkan kamera langsung ke piring makananmu, lalu klik *'Analisis Jepretan Kamera'*.
            * **Cara B (Unggah Foto Galeri):** Pilih foto makanan dari galeri HP Anda.
            * **Cara C (Tulis Teks Bebas):** Ketik apa saja yang Anda makan (misal: *'1 piring nasi padang rendang dan daun singkong'*).
            * **Simpan ke Diary:** Di bawah hasil analisa, pilih waktu makan (Sarapan/Makan Siang/Makan Malam) lalu klik **'💾 Simpan ke Buku Harian'**.
            """)

        with st.container(border=True):
            st.markdown("### 4️⃣ **Evaluasi Tren & Pola Makan Anda**")
            st.markdown("""
            * Buka tab **'📊 DASHBOARD REKAPAN'** untuk melihat:
              * **Cincin Aktivitas Kalori Hari Ini** (berapa sisa kuota kalori Anda).
              * **Grafik Tren 7 Hari & 30 Hari** (mendeteksi hari di mana Anda makan berlebih).
              * **Tombol Bagikan ke WhatsApp** untuk mengirim laporan diet harian ke pelatih, teman, atau keluarga!
            """)

    st.markdown("---")
    st.markdown("### 💡 **Pertanyaan Umum (FAQ)**")
    with st.expander("❓ Apakah data makanan saya aman dan privat?"):
        st.write("Ya, data riwayat makanan Anda hanya terikat pada akun Google atau username Anda sendiri dan tidak dapat diakses oleh publik.")
    with st.expander("❓ Bagaimana cara kerja kuota scan foto makanan?"):
        st.write("Pengguna Free mendapatkan 3x scan foto kamera/galeri setiap hari secara gratis. Pencarian database lab dan pencatatan via teks bersifat 100% tanpa batas selamanya. Anda bisa mengklaim 30 Hari Gratis PRO untuk menikmati scan foto tanpa batas.")
    with st.expander("❓ Dari mana data kalori dan nutrisi ini diambil?"):
        st.write("Data nutrisi kami 100% berbasis Tabel Komposisi Pangan Indonesia (TKPI) resmi Kementerian Kesehatan RI, USDA FoodData Central, dan NilaiGizi.")

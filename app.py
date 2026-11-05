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

from gemini_extractor import analyze_food_image, analyze_food_text
from nutrition_engine import calculate_dish_nutrition
from db_history import init_user_history_tables, get_or_create_user, log_meal, get_user_history_stats, update_calorie_target

init_user_history_tables()

st.set_page_config(
    page_title="Gizi.AI - Nutrisi Cerdas & Health Diary",
    page_icon="🍏",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Styling Konsep A: Clean Apple Healthtech (Serba Putih Lembut, Hijau Emerald, Kartu Soft Shadow)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    /* Background Utama */
    .stApp {
        background-color: #f8fafc;
    }
    
    /* Apple Health Ring Card */
    .apple-ring-card {
        background: #ffffff;
        border-radius: 24px;
        padding: 1.8rem;
        box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.05), 0 2px 6px -1px rgba(0, 0, 0, 0.02);
        border: 1px solid #e2e8f0;
        margin-bottom: 1.5rem;
    }
    
    .ring-title {
        font-size: 0.88rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    
    .ring-val {
        font-size: 2.3rem;
        font-weight: 800;
        color: #0f172a;
        margin: 0.3rem 0;
    }
    
    .ring-sub {
        font-size: 0.95rem;
        color: #64748b;
    }

    /* Modern Macro Cards (Gaya Apple Health) */
    .macro-pill {
        background: #ffffff;
        border-radius: 20px;
        padding: 1.2rem 1rem;
        border: 1px solid #edf2f7;
        box-shadow: 0 4px 12px rgba(0,0,0,0.03);
        text-align: center;
    }
    .macro-num {
        font-size: 1.6rem;
        font-weight: 800;
        margin: 0.2rem 0;
    }
    .macro-lbl {
        font-size: 0.78rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Tip Alert */
    .apple-tip {
        background: #f0fdf4;
        border: 1px solid #bbf7d0;
        border-left: 5px solid #10b981;
        border-radius: 14px;
        padding: 1rem 1.2rem;
        color: #166534;
        font-size: 0.93rem;
        line-height: 1.5;
        margin: 1.2rem 0;
    }
    
    /* Tab Styling: Super Jelas, Besar & Modern */
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
        border: none !important;
        transition: all 0.2s ease !important;
    }
    
    button[data-baseweb="tab"][aria-selected="true"] {
        background-color: #ffffff !important;
        color: #0f172a !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08) !important;
    }

    /* Tombol Bersih */
    .stButton>button {
        border-radius: 14px;
        font-weight: 700;
        padding: 0.6rem 1.4rem;
        box-shadow: 0 2px 6px rgba(0,0,0,0.04);
    }
</style>
""", unsafe_allow_html=True)

# Sesi Akun Pengguna
if "user" not in st.session_state:
    st.session_state["user"] = get_or_create_user("Tamu (Demo)", display_name="Tamu Sehat", auth_provider="local")

if "nutrition_data" not in st.session_state:
    st.session_state["nutrition_data"] = None

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
        
    with st.expander("🔑 Masuk / Ganti Akun Pribadi"):
        st.markdown("**Opsi 1: Kaitkan Akun Google**")
        google_email = st.text_input("Ketik Email Google Anda:", placeholder="contoh@gmail.com")
        if st.button("🔗 Masuk dengan Google", use_container_width=True):
            if "@" in google_email:
                st.session_state["user"] = get_or_create_user(google_email.strip(), auth_provider="google")
                st.success("Berhasil masuk dengan akun Google!")
                st.rerun()
            else:
                st.error("Format email tidak valid.")
                
        st.markdown("---")
        st.markdown("**Opsi 2: Masuk via Nama / Username**")
        local_user = st.text_input("Username:", placeholder="misal: nabillah")
        if st.button("Ganti Akun", use_container_width=True):
            if local_user.strip():
                st.session_state["user"] = get_or_create_user(local_user.strip(), auth_provider="local")
                st.rerun()

    # Target Kalori Harian
    st.markdown("---")
    st.markdown("### 🎯 **Target Kalori Harian**")
    current_target = float(current_user.get("daily_calorie_target") or 2000.0)
    new_target = st.number_input("Target Kalori (kkal):", min_value=1000, max_value=4000, value=int(current_target), step=50)
    if new_target != current_target:
        update_calorie_target(current_user["user_id"], float(new_target))
        st.session_state["user"]["daily_calorie_target"] = float(new_target)
        st.toast("Target kalori diperbarui!")

# Header Brand Utama dengan Logo Menonjol & Kotak Login Akun Langsung di Halaman Utama
current_user = st.session_state["user"]
is_google = current_user.get("auth_provider") == "google"

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
            <div style="display: flex; align-items: center; gap: 10px;">
                <h1 style="font-size: 2.5rem; font-weight: 800; color: #0f172a; margin: 0; letter-spacing: -0.02em;">Gizi.AI</h1>
                <span style="background: rgba(16, 185, 129, 0.12); color: #059669; font-size: 0.8rem; font-weight: 800; padding: 0.35rem 0.8rem; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.05em; border: 1px solid rgba(16, 185, 129, 0.25);">
                    LAB KEMENKES
                </span>
            </div>
            <p style="margin: 0.2rem 0 0 0; color: #64748b; font-size: 1.05rem; font-weight: 500;">
                Kalkulator & Diary Nutrisi Makanan Indonesia Berbasis Data Uji Lab Resmi
            </p>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_head2:
    with st.container(border=True):
        st.markdown(f"👤 **Akun Aktif:** `{current_user['display_name']}`")
        with st.popover("🔑 Masuk Akun Google / Username", use_container_width=True):
            st.markdown("##### 🔗 Kaitkan Email Google Anda")
            in_email = st.text_input("Email Google / Gmail:", placeholder="nama@gmail.com", key="pop_email")
            if st.button("Simpan & Masuk Akun Ini", type="primary", use_container_width=True, key="pop_btn"):
                if "@" in in_email:
                    st.session_state["user"] = get_or_create_user(in_email.strip(), auth_provider="google")
                    st.rerun()
                elif in_email.strip():
                    st.session_state["user"] = get_or_create_user(in_email.strip(), auth_provider="local")
                    st.rerun()
            st.caption("Data makanan harian Anda tersimpan permanen dan terikat pada email ini.")

# Navigasi Menu Atas (Clean Tabs dengan Ikon Jelas)
tab_diary, tab_scanner = st.tabs([
    "📊  DASHBOARD REKAPAN (HARI / MINGGU / BULAN)",
    "📸  CATAT MAKANAN BARU (FOTO & TEKS)"
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

    # Riwayat Makan Hari Ini
    st.markdown("### 📝 **Buku Harian Makan Hari Ini**")
    if stats["today_meals"]:
        diary_rows = []
        for m in stats["today_meals"]:
            time_str = datetime.strptime(m["logged_at"], "%Y-%m-%d %H:%M:%S").strftime("%H:%M") if " " in m["logged_at"] else m["logged_at"]
            diary_rows.append({
                "Jam": time_str,
                "Nama Makanan": m["dish_name"],
                "Kalori": f"{m['energy_kcal']} kkal",
                "Protein": f"{m['protein_g']} g",
                "Lemak": f"{m['fat_g']} g",
                "Karbo": f"{m['carb_g']} g",
                "Keterangan": m["photo_caption"] or "-"
            })
        st.dataframe(diary_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("Belum ada makanan yang dicatat hari ini.")

# ================= TAB 2: CATAT MAKANAN BARU =================
with tab_scanner:
    # Ambil API key otomatis
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key and hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
        api_key = st.secrets["GEMINI_API_KEY"]

    subtab_foto, subtab_teks = st.tabs(["📸 Ambil / Unggah Foto", "✍️ Tulis Menu Harian"])
    
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
                if st.button("🚀 Analisis Gizi Foto", type="primary", use_container_width=True, key="btn_foto"):
                    with st.spinner("Menganalisis visual foto makanan..."):
                        try:
                            res = analyze_food_image(im, caption=p_caption, api_key=api_key)
                            res["user_caption"] = p_caption
                            st.session_state["nutrition_data"] = res
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal memproses gambar: {e}")
            else:
                st.info("💡 **Tips:** Foto piring makan dari atas agar semua lauk dan sayuran tampak jelas.")

    with subtab_teks:
        t_input = st.text_area("Tuliskan menu makanan:", placeholder="Contoh: 1 piring gado-gado lontong pakai telur rebus dan bumbu kacang", height=100)
        if st.button("Hitung Gizi Menu", type="primary", use_container_width=True, key="btn_teks"):
            if t_input.strip():
                with st.spinner("Menghitung nilai gizi dari database lab..."):
                    try:
                        res = analyze_food_text(t_input, api_key=api_key)
                        res["user_caption"] = t_input
                        st.session_state["nutrition_data"] = res
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal memproses teks: {e}")

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
        
        # Tombol Simpan ke Akun Pribadi
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button(f"💾 Simpan ke Buku Harian ({st.session_state['user']['display_name']})", type="primary", use_container_width=True):
            log_meal(
                user_id=st.session_state["user"]["user_id"],
                dish_name=data.get("dish_name", "Menu Sehat"),
                totals=t_tot,
                multiplier=p_mult,
                caption=data.get("user_caption", "")
            )
            st.success(f"Berhasil dicatat ke akun {st.session_state['user']['display_name']}! Silakan cek tab Dashboard.")
            st.session_state["nutrition_data"] = None
            st.rerun()

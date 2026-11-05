"""
Aplikasi Gizi.AI Modern & Clean UI
Desain antarmuka bersih, kartu makronutrien visual, progress bar kalori, dan pengalaman mobile-friendly.
"""

import streamlit as st
from PIL import Image
import os
import json

from gemini_extractor import analyze_food_image, analyze_food_text
from nutrition_engine import calculate_dish_nutrition

st.set_page_config(
    page_title="Gizi.AI - Cek Nutrisi Makanan Cepat & Akurat",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS Styling: Modern Cards, Clean Typography, & Gradient Accents
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }
    
    /* Header Container */
    .hero-container {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 20px;
        padding: 2.2rem 2rem;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
    }
    .hero-badge {
        display: inline-block;
        background: rgba(16, 185, 129, 0.15);
        color: #34d399;
        font-size: 0.82rem;
        font-weight: 700;
        padding: 0.35rem 0.85rem;
        border-radius: 9999px;
        border: 1px solid rgba(52, 211, 153, 0.3);
        margin-bottom: 0.8rem;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    .hero-title {
        color: #ffffff;
        font-size: 2.4rem;
        font-weight: 800;
        margin-bottom: 0.5rem;
        line-height: 1.2;
    }
    .hero-subtitle {
        color: #94a3b8;
        font-size: 1.05rem;
        font-weight: 400;
        max-width: 750px;
        line-height: 1.6;
    }
    
    /* Macro Cards */
    .macro-card {
        background: #1e293b;
        border-radius: 16px;
        padding: 1.25rem 1rem;
        border: 1px solid rgba(255, 255, 255, 0.06);
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .macro-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 20px rgba(0,0,0,0.3);
    }
    .macro-icon {
        font-size: 1.6rem;
        margin-bottom: 0.3rem;
    }
    .macro-val {
        font-size: 1.7rem;
        font-weight: 800;
        color: #f8fafc;
        margin: 0.2rem 0;
    }
    .macro-label {
        font-size: 0.8rem;
        font-weight: 600;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Health Tip Card */
    .tip-box {
        background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(5, 150, 105, 0.05) 100%);
        border-left: 4px solid #10b981;
        border-radius: 12px;
        padding: 1rem 1.25rem;
        margin: 1.2rem 0;
        color: #e2e8f0;
        font-size: 0.95rem;
        line-height: 1.5;
    }

    /* Primary Action Buttons */
    .stButton>button {
        border-radius: 12px;
        font-weight: 700;
        padding: 0.6rem 1.5rem;
        transition: all 0.2s ease;
    }
</style>
""", unsafe_allow_html=True)

# Ambil API key otomatis dari secrets Streamlit Cloud atau file .env
configured_api_key = os.environ.get("GEMINI_API_KEY", "")
if not configured_api_key and hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
    configured_api_key = st.secrets["GEMINI_API_KEY"]

# Sidebar Ringkas & Bersih
with st.sidebar:
    st.markdown("### 🥗 **Gizi.AI Control**")
    if configured_api_key:
        st.success("🟢 AI Engine Aktif")
        api_key = configured_api_key
        with st.expander("Ganti Custom API Key (Opsional)"):
            custom_key = st.text_input("API Key Baru:", type="password")
            if custom_key:
                api_key = custom_key
    else:
        st.warning("⚠️ API Key Belum Ditemukan")
        api_key = st.text_input("Masukkan Google AI Studio API Key:", type="password")
        st.caption("Dapatkan API Key gratis di [aistudio.google.com](https://aistudio.google.com)")

    st.markdown("---")
    st.markdown("""
    **Standar Pangan Terverifikasi:**
    - 🏛️ **TKPI Kemenkes RI** (1.194 bahan pangan lab)
    - 📏 **URT Porsi Rumah Tangga Indonesia**
    - ⚡ **Zero-Token Engine** (Akurasi Matematika 100%)
    """)

# Hero Banner
st.markdown("""
<div class="hero-container">
    <div class="hero-badge">⚡ Standar Laboratorium Kemenkes RI</div>
    <div class="hero-title">Hitung Nutrisi Makanan Seketika</div>
    <div class="hero-subtitle">
        Cukup foto makanan atau ketik menu harianmu. AI cerdas akan mengenali porsi nusantara dan menghitung kalori serta makronutrien secara akurat tanpa ribet menimbang.
    </div>
</div>
""", unsafe_allow_html=True)

# Tabs Input: Foto, Teks, Demo
tab_foto, tab_teks, tab_demo = st.tabs([
    "📸  Ambil / Unggah Foto",
    "✍️  Tulis Menu Makanan",
    "⚡  Coba Menu Populer (Demo)"
])

# State penampung hasil analisis
if "nutrition_data" not in st.session_state:
    st.session_state["nutrition_data"] = None

with tab_foto:
    col_up1, col_up2 = st.columns([1, 1], gap="large")
    with col_up1:
        uploaded_file = st.file_uploader(
            "Pilih foto makanan dari galeri atau kamera HP:",
            type=["jpg", "jpeg", "png", "webp"],
            help="Format JPG, PNG, atau WebP"
        )
        if uploaded_file:
            img = Image.open(uploaded_file)
            st.image(img, caption="Preview Foto Makanan", use_container_width=True)
    with col_up2:
        if uploaded_file:
            st.markdown("#### Siap Menganalisis?")
            st.caption("AI akan memindai objek piring, jenis lauk, sayuran, dan bumbu pelengkap.")
            if st.button("🚀 Analisis Gizi Foto Sekarang", type="primary", use_container_width=True):
                if not api_key:
                    st.error("Silakan masukkan Google AI Studio API Key terlebih dahulu.")
                else:
                    with st.spinner("🔍 Memindai foto & mencocokkan ke 1.194 data lab Kemenkes..."):
                        try:
                            res = analyze_food_image(img, api_key=api_key)
                            st.session_state["nutrition_data"] = res
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal memproses gambar: {e}")
        else:
            st.info("💡 **Tips:** Ambil foto makanan dari sudut agak atas agar seluruh komponen di piring terlihat jelas oleh AI.")

with tab_teks:
    col_t1, col_t2 = st.columns([1.5, 1], gap="large")
    with col_t1:
        text_input = st.text_area(
            "Apa yang kamu makan hari ini?",
            placeholder="Contoh: 1 porsi gado-gado lontong pakai telur rebus dan bumbu kacang",
            height=130
        )
        if st.button("Hitung Nutrisi Menu Ini", type="primary", use_container_width=True):
            if not api_key:
                st.error("Silakan masukkan Google AI Studio API Key terlebih dahulu.")
            elif not text_input.strip():
                st.warning("Silakan ketik menu makanan terlebih dahulu.")
            else:
                with st.spinner("📊 Menghitung komposisi gizi dan porsi URT..."):
                    try:
                        res = analyze_food_text(text_input, api_key=api_key)
                        st.session_state["nutrition_data"] = res
                        st.rerun()
                    except Exception as e:
                        st.error(f"Gagal memproses teks: {e}")
    with col_t2:
        st.markdown("""
        **Contoh penulisan yang akurat:**
        - *"Nasi putih 1 centong + dada ayam bakar + tahu goreng + sambal"*
        - *"Kopi hitam tanpa gula 1 cangkir"*
        - *"1 mangkok bakso sapi komplit pakai mie kuning"*
        """)

with tab_demo:
    col_d1, col_d2 = st.columns([1.5, 1], gap="large")
    with col_d1:
        st.markdown("#### Uji Coba Cepat Tanpa Mengetik")
        demo_option = st.selectbox("Pilih menu masakan Indonesia:", [
            "Gado-Gado Lengkap (Lontong + Telur Rebus + Bumbu Kacang + Kerupuk)",
            "Nasi Putih + Dada Ayam Bakar + Tahu Goreng + Sambal",
            "Kopi Hitam Polos Tanpa Gula (1 Cangkir)"
        ])
        if st.button("Tampilkan Hasil Gizi Demo", use_container_width=True):
            if "Gado-Gado" in demo_option:
                st.session_state["nutrition_data"] = {
                    "dish_name": "Gado-Gado Lengkap",
                    "confidence": "high",
                    "portion_category": "sedang",
                    "components": [
                        {"name": "Lontong", "weight_g": 100},
                        {"name": "Sayuran rebus campur", "weight_g": 120},
                        {"name": "Tahu goreng", "weight_g": 40},
                        {"name": "Bumbu kacang gado-gado", "weight_g": 50},
                        {"name": "Telur ayam rebus", "weight_g": 55},
                        {"name": "Kerupuk putih kaleng", "weight_g": 15}
                    ],
                    "health_tip": "Bumbu kacang merupakan penyumbang kalori dan lemak utama. Kurangi porsi bumbu jika sedang program defisit kalori."
                }
            elif "Ayam Bakar" in demo_option:
                st.session_state["nutrition_data"] = {
                    "dish_name": "Nasi Ayam Bakar Komplit",
                    "confidence": "high",
                    "portion_category": "sedang",
                    "components": [
                        {"name": "Nasi putih", "weight_g": 150},
                        {"name": "Ayam bakar", "weight_g": 80},
                        {"name": "Tahu goreng", "weight_g": 40},
                        {"name": "Sambal terasi", "weight_g": 15}
                    ],
                    "health_tip": "Pilihan menu tinggi protein yang sangat baik untuk pembentukan otot dan rasa kenyang lebih lama."
                }
            else:
                st.session_state["nutrition_data"] = {
                    "dish_name": "Kopi Hitam Polos",
                    "confidence": "high",
                    "portion_category": "kecil",
                    "components": [
                        {"name": "Air Mineral", "weight_g": 150},
                        {"name": "Kopi hitam polos tanpa gula", "weight_g": 10}
                    ],
                    "health_tip": "Kopi hitam tanpa gula kaya antioksidan alami dan praktis nol kalori, sangat cocok saat puasa intermiten."
                }
            st.rerun()
    with col_d2:
        st.caption("Pilihan di atas menggunakan data baku langsung dari pangkalan data TKPI Kemenkes.")

# SECTION: HASIL ANALISIS NUTRISI
if st.session_state["nutrition_data"]:
    data = st.session_state["nutrition_data"]
    
    st.markdown("---")
    
    # Header Hasil
    head_col1, head_col2 = st.columns([2, 1])
    with head_col1:
        st.markdown(f"## 🍽️ {data.get('dish_name', 'Menu Makanan')}")
        conf = data.get("confidence", "high").upper()
        p_cat = data.get("portion_category", "sedang").capitalize()
        st.caption(f"Tingkat Keyakinan AI: **{conf}** | Porsi Dasar: **{p_cat}**")
    
    with head_col2:
        if st.button("🔄 Reset / Hitung Menu Lain", use_container_width=True):
            st.session_state["nutrition_data"] = None
            st.rerun()

    # Slider Porsi Interaktif
    st.markdown("#### ⚖️ Sesuaikan Porsi yang Kamu Makan")
    portion_slider = st.select_slider(
        "Geser untuk menyesuaikan ukuran porsi riil:",
        options=[0.7, 1.0, 1.3, 1.5],
        value=1.0,
        format_func=lambda x: {
            0.7: "Porsi Sedikit (~0.7x)",
            1.0: "Porsi Standar (1.0x)",
            1.3: "Porsi Agak Banyak (1.3x)",
            1.5: "Porsi Jumbo (1.5x)"
        }[x],
        label_visibility="collapsed"
    )

    # Kalkulasi deterministik dari 1.194 Database Lab TKPI
    calc_result = calculate_dish_nutrition(data.get("components", []), portion_multiplier=portion_slider)
    totals = calc_result["totals"]

    # Saran Gizi dari AI
    if data.get("health_tip"):
        st.markdown(f"""
        <div class="tip-box">
            💡 <strong>Rekomendasi Gizi:</strong> {data['health_tip']}
        </div>
        """, unsafe_allow_html=True)

    # Kartu Visual Makronutrien
    st.markdown("### 📊 Ringkasan Nutrisi")
    m1, m2, m3, m4, m5 = st.columns(5)
    
    with m1:
        st.markdown(f"""
        <div class="macro-card">
            <div class="macro-icon">🔥</div>
            <div class="macro-val">{totals['energy_kcal']}</div>
            <div class="macro-label">Kalori (kkal)</div>
        </div>
        """, unsafe_allow_html=True)

    with m2:
        st.markdown(f"""
        <div class="macro-card">
            <div class="macro-icon">🥩</div>
            <div class="macro-val" style="color: #60a5fa;">{totals['protein_g']}g</div>
            <div class="macro-label">Protein</div>
        </div>
        """, unsafe_allow_html=True)

    with m3:
        st.markdown(f"""
        <div class="macro-card">
            <div class="macro-icon">🥑</div>
            <div class="macro-val" style="color: #fbbf24;">{totals['fat_g']}g</div>
            <div class="macro-label">Lemak</div>
        </div>
        """, unsafe_allow_html=True)

    with m4:
        st.markdown(f"""
        <div class="macro-card">
            <div class="macro-icon">🍚</div>
            <div class="macro-val" style="color: #34d399;">{totals['carb_g']}g</div>
            <div class="macro-label">Karbohidrat</div>
        </div>
        """, unsafe_allow_html=True)

    with m5:
        st.markdown(f"""
        <div class="macro-card">
            <div class="macro-icon">🥬</div>
            <div class="macro-val" style="color: #a78bfa;">{totals['fiber_g']}g</div>
            <div class="macro-label">Serat</div>
        </div>
        """, unsafe_allow_html=True)

    # Tabel Rincian Komponen Bahan
    st.markdown("### 📋 Rincian Komposisi Bahan & Standar Lab")
    table_rows = []
    for it in calc_result["items"]:
        table_rows.append({
            "Bahan": it["input_name"],
            "Referensi Lab TKPI": it["tkpi_matched_name"],
            "Berat": f"{it['weight_g']} g",
            "Kalori": f"{it['energy_kcal']} kkal",
            "Protein": f"{it['protein_g']} g",
            "Lemak": f"{it['fat_g']} g",
            "Karbo": f"{it['carb_g']} g"
        })
    st.dataframe(table_rows, use_container_width=True, hide_index=True)

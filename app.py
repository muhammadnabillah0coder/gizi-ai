"""
Aplikasi Prototipe Estimasi Gizi Cerdas (Hybrid AI + Lab TKPI Kemenkes)
Dijalankan dengan: streamlit run app.py
"""

import streamlit as st
from PIL import Image
import os
import json

from gemini_extractor import analyze_food_image, analyze_food_text
from nutrition_engine import calculate_dish_nutrition

st.set_page_config(
    page_title="Gizi.AI Clone - Lab Nutrition Calculator",
    page_icon="🥗",
    layout="wide"
)

st.title("🥗 Gizi.AI: Smart Food & Nutrition Estimator")
st.markdown("""
*Estimasi gizi makanan Indonesia berbasis **Standar Porsi URT & Data Uji Lab TKPI Kementerian Kesehatan RI**.*
Didukung oleh **Google AI Studio (Gemini Flash)** dengan arsitektur **Hybrid Hemat Token**.
""")

# Sidebar: Pengaturan API Key & Info
with st.sidebar:
    st.header("⚙️ Konfigurasi")
    api_key = st.text_input("Google AI Studio API Key:", type="password", value=os.environ.get("GEMINI_API_KEY", ""))
    st.caption("Dapatkan API Key gratis di [aistudio.google.com](https://aistudio.google.com)")
    
    st.markdown("---")
    st.subheader("📚 Sumber Data Terpercaya")
    st.markdown("""
    - **Lab Nutrisi:** Tabel Komposisi Pangan Indonesia (TKPI) Kemenkes RI.
    - **Porsi:** Ukuran Rumah Tangga (URT) Nasional.
    - **Akurasi Hitung:** 100% Deterministik (0 Token AI untuk kalkulasi).
    """)

# Input Mode: Foto atau Teks
tab_foto, tab_teks, tab_demo = st.tabs(["📸 Unggah Foto Makanan", "✍️ Input Teks Manual", "⚡ Demo Cepat (Tanpa API Key)"])

ai_result = None

with tab_foto:
    uploaded_file = st.file_uploader("Pilih foto makanan (JPG / PNG / WebP):", type=["jpg", "jpeg", "png", "webp"])
    if uploaded_file:
        img = Image.open(uploaded_file)
        col_img, col_btn = st.columns([1, 1])
        with col_img:
            st.image(img, caption="Foto Makanan Anda", use_container_width=True)
        with col_btn:
            if st.button("🔍 Analisis Foto Makanan", type="primary", use_container_width=True):
                if not api_key:
                    st.error("Silakan masukkan Google AI Studio API Key di sidebar terlebih dahulu.")
                else:
                    with st.spinner("AI sedang mendeteksi bahan & menaksir porsi..."):
                        try:
                            ai_result = analyze_food_image(img, api_key=api_key)
                            st.session_state["nutrition_data"] = ai_result
                        except Exception as e:
                            st.error(f"Gagal memproses gambar: {e}")

with tab_teks:
    text_input = st.text_area("Tulis menu makanan harian Anda:", placeholder="Contoh: 1 porsi gado-gado pakai lontong, telur rebus 1 butir, kerupuk, dan bumbu kacang")
    if st.button("Hitung Gizi dari Teks", use_container_width=True):
        if not api_key:
            st.error("Silakan masukkan Google AI Studio API Key di sidebar terlebih dahulu.")
        else:
            with st.spinner("Menganalisis teks menu makanan..."):
                try:
                    ai_result = analyze_food_text(text_input, api_key=api_key)
                    st.session_state["nutrition_data"] = ai_result
                except Exception as e:
                    st.error(f"Gagal memproses teks: {e}")

with tab_demo:
    st.info("Pilih skenario siap pakai untuk menguji kalkulator lab nutrisi secara langsung tanpa API Key:")
    demo_option = st.selectbox("Pilih Menu Demo:", [
        "Gado-Gado Lengkap (Lontong + Telur Rebus + Bumbu Kacang + Kerupuk)",
        "Nasi Putih + Ayam Goreng Paha + Tahu Goreng + Sambal",
        "Bakso Sapi Komplit (Mie Kuning + Bakso + Sayur)"
    ])
    
    if st.button("Jalankan Simulasi Demo", use_container_width=True):
        if "Gado-Gado" in demo_option:
            st.session_state["nutrition_data"] = {
                "dish_name": "Gado-Gado Lengkap",
                "confidence": "high",
                "portion_category": "sedang",
                "components": [
                    {"name": "Lontong", "weight_g": 100},
                    {"name": "Sayuran rebus", "weight_g": 120},
                    {"name": "Tahu goreng", "weight_g": 40},
                    {"name": "Bumbu kacang", "weight_g": 50},
                    {"name": "Telur rebus", "weight_g": 55},
                    {"name": "Kerupuk", "weight_g": 15}
                ],
                "health_tip": "Bumbu kacang menyumbang lemak dan kalori utama. Kurangi bumbu jika sedang program defisit kalori."
            }
        elif "Ayam Goreng" in demo_option:
            st.session_state["nutrition_data"] = {
                "dish_name": "Nasi Ayam Goreng Komplit",
                "confidence": "high",
                "portion_category": "sedang",
                "components": [
                    {"name": "Nasi putih", "weight_g": 150},
                    {"name": "Ayam goreng paha/dada", "weight_g": 80},
                    {"name": "Tahu goreng", "weight_g": 40},
                    {"name": "Sambal terasi", "weight_g": 15},
                    {"name": "Timun mentah", "weight_g": 30}
                ],
                "health_tip": "Tinggi protein, namun perhatikan lemak jenuh dari minyak goreng."
            }
        else:
            st.session_state["nutrition_data"] = {
                "dish_name": "Bakso Sapi Komplit",
                "confidence": "high",
                "portion_category": "sedang",
                "components": [
                    {"name": "Bakso sapi komplit", "weight_g": 350},
                    {"name": "Bawang goreng", "weight_g": 5}
                ],
                "health_tip": "Perhatikan kandungan natrium/garam tinggi pada kuah bakso."
            }

# Render Hasil Kalkulasi Nutrisi
if "nutrition_data" in st.session_state and st.session_state["nutrition_data"]:
    data = st.session_state["nutrition_data"]
    
    st.markdown("---")
    st.header(f"🍽️ Hasil Analisis: {data.get('dish_name', 'Menu Makanan')}")
    
    col_stat1, col_stat2, col_stat3 = st.columns([1, 1, 2])
    with col_stat1:
        st.metric("Tingkat Keyakinan AI", data.get("confidence", "high").upper())
    with col_stat2:
        st.metric("Kategori Porsi Awal", data.get("portion_category", "sedang").capitalize())
    with col_stat3:
        if data.get("health_tip"):
            st.success(f"💡 **Saran Gizi:** {data['health_tip']}")

    # Slider Penyesuaian Porsi (Interactive Re-calculation tanpa makan token)
    st.subheader("⚖️ Sesuaikan Porsi Anda")
    portion_slider = st.select_slider(
        "Pilih estimasi porsi riil yang Anda makan:",
        options=[0.7, 1.0, 1.3, 1.5],
        value=1.0,
        format_func=lambda x: {
            0.7: "Porsi Kecil / Setengah (~0.7x)",
            1.0: "Porsi Standar / Normal (1.0x)",
            1.3: "Porsi Kenyang / Agak Banyak (1.3x)",
            1.5: "Porsi Jumbo (1.5x)"
        }[x]
    )

    # Kalkulasi deterministik dari database lab TKPI
    calc_result = calculate_dish_nutrition(data.get("components", []), portion_multiplier=portion_slider)
    totals = calc_result["totals"]

    # Dashboard Ringkasan Makronutrien
    st.markdown("### 📊 Ringkasan Nutrisi (Data Lab TKPI Kemenkes)")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🔥 Total Kalori", f"{totals['energy_kcal']} kkal")
    c2.metric("🥩 Protein", f"{totals['protein_g']} g")
    c3.metric("🥑 Lemak", f"{totals['fat_g']} g")
    c4.metric("🍚 Karbohidrat", f"{totals['carb_g']} g")
    c5.metric("🥬 Serat", f"{totals['fiber_g']} g")

    # Tabel Rincian Komponen Bahan
    st.markdown("### 📋 Rincian Komposisi Bahan & Bobot")
    table_rows = []
    for it in calc_result["items"]:
        table_rows.append({
            "Bahan Terdeteksi": it["input_name"],
            "Referensi Lab TKPI": it["tkpi_matched_name"],
            "Berat": f"{it['weight_g']} g",
            "Kalori": f"{it['energy_kcal']} kkal",
            "Protein": f"{it['protein_g']} g",
            "Lemak": f"{it['fat_g']} g",
            "Karbo": f"{it['carb_g']} g"
        })
    st.dataframe(table_rows, use_container_width=True)

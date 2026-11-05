# Gizi.AI: Smart Food & Lab Nutrition Estimator
Implementasi aplikasi web estimasi gizi makanan berbasis standar **7 Layer Production Maturity Roadmap** (Bottom-Up Engineering).

---

## 7 Lapisan Kesiapan Produksi (Production Maturity Checklist)

- [x] **Layer 1: Satu File (Entry Point):** Prototipe antarmuka [`app.py`](app.py) yang interaktif, mendukung upload foto, input teks, dan slider porsi.
- [x] **Layer 2: Rules File (AI Guidelines):** Panduan [`AGENTS.md`](AGENTS.md) untuk memastikan AI tidak mengarang angka gizi dan tetap hemat token.
- [x] **Layer 3: Automated Test:** Unit test [`tests/test_nutrition.py`](tests/test_nutrition.py) untuk menjamin akurasi formula gizi lolos 100%.
- [x] **Layer 4: Database Persistence:** Basis data SQLite [`tkpi_nutrition.db`](tkpi_nutrition.db) bersumber dari data uji laboratorium resmi **TKPI Kemenkes RI** per 100g BDD.
- [x] **Layer 5: Environment Variables:** Pemisahan rahasia via [`.env.example`](.env.example) & [`.gitignore`](.gitignore) agar API key aman.
- [x] **Layer 6: One-Link Deployment:** Siap di-deploy dengan 1 klik ke Streamlit Community Cloud, HuggingFace Spaces, atau Railway.
- [x] **Layer 7: Monitoring & Alerting ke HP:** Modul [`alert_manager.py`](alert_manager.py) untuk mengirim notifikasi instan ke Telegram HP jika terjadi error fatal.

---

## Cara Menjalankan Secara Lokal

1. **Install dependensi:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Setup file rahasia (.env):**
   Salin `.env.example` menjadi `.env` lalu masukkan API Key Google AI Studio Anda:
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```
3. **Jalankan Unit Test:**
   ```bash
   python tests/test_nutrition.py
   ```
4. **Jalankan Aplikasi Web:**
   ```bash
   streamlit run app.py
   ```

Aplikasi akan terbuka di browser pada alamat `http://localhost:8501`.

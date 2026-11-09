# Nutrisi Cerdas: Precision Food & Lab Nutrition Intelligence

Aplikasi web estimasi nutrisi pangan, kalkulator makronutrien deterministik, dan diary pola makan cerdas berbasis rujukan baku laboratorium **Tabel Komposisi Pangan Indonesia (TKPI) Kemenkes RI** serta **USDA FoodData Central**.

Dibangun dengan arsitektur **Bottom-Up Engineering (7-Layer Production Maturity Roadmap)** untuk menjamin akurasi klinis, performa serverless yang efisien, dan zero-hallucination.

---

## 🏛️ Arsitektur Orisinal Nutrisi Cerdas (The 4-Pillar Architecture)

Berbeda dengan aplikasi generik yang sekadar melempar prompt bebas ke LLM dan menghasilkan angka kalori halusinasi, **Nutrisi Cerdas** memisahkan secara tegas antara *Computer Vision* dan *Clinical Verification Math*:

```
               [ Input Pengguna ]
           /           |          \
   [ Kamera HP ]   [ Teks Bebas ]   [ Barcode EAN-13 ]
         |             |                   |
         v             v                   |
  +--------------------------+             |
  |  Gemini Vision & Parser  |             |
  | (Hanya Uraikan Komponen  |             |
  |   & Taksiran Gram URT)   |             |
  +--------------------------+             |
               |                           |
               +-------------+-------------+
                             |
                             v
           +-----------------------------------+
           |    Clinical Verification Core     |
           |   (0-Token Math Deterministic)    |
           |  - TKPI Kemenkes RI (1.300+ item) |
           |  - Database Pangan Ritel BPOM     |
           |  - USDA FoodData Central          |
           +-----------------------------------+
                             |
                             v
           +-----------------------------------+
           |    Apple-Grade Health Analytics   |
           |  - Activity Ring Kalori & Makro   |
           |  - Daily Water Tracker (2000ml)   |
           |  - Multi-User History (SQLite)    |
           +-----------------------------------+
```

### 1. Zero-Token Deterministic Math Calculation
AI generatif (Gemini Vision) dilarang menghitung kalori dari nol. AI hanya bertugas mengekstrak identitas makanan dan estimasi gramatur porsi Rumah Tangga (URT). Angka kalori, protein, lemak, karbohidrat, dan serat 100% dihitung secara deterministik menggunakan data uji lab resmi per 100g BDD (Bagian Dapat Dimakan).

### 2. Dual Verification Input (Vision + Barcode Scanner)
Mendukung input visual makanan tradisional/rumahan sekaligus verifikasi barcode EAN-13 produk ritel kemasan Indonesia yang sudah terdaftar di pangkalan data ritel.

### 3. Adaptive URT Portion Sliders
Pengguna tidak perlu menimbang makanan dengan timbangan digital. UI menyediakan slider adaptif instan (0.7x Porsi Sedikit, 1.0x Normal, 1.3x Kenyang, 1.5x Jumbo) yang menghitung ulang nilai gizi secara lokal tanpa konsumsi token API tambahan.

### 4. Apple Health Activity Ring UI
Visualisasi ring 3 dimensi untuk target kalori harian (BMR/TDEE personal), status defisit/surplus, makronutrien seimbang, dan hidrasi air minum harian.

---

## 📋 7 Lapisan Kesiapan Produksi (Production Maturity Checklist)

- [x] **Layer 1: Satu File (Entry Point):** Antarmuka utama terintegrasi [`app.py`](app.py) yang responsif untuk mobile dan desktop.
- [x] **Layer 2: Rules File (AI Guidelines):** Pedoman teknis [`AGENTS.md`](AGENTS.md) untuk menjaga batas cakupan AI dan mencegah halusinasi klinis.
- [x] **Layer 3: Automated Test:** Unit test [`tests/test_nutrition.py`](tests/test_nutrition.py) untuk memastikan formula perhitungan matematika akurat 100%.
- [x] **Layer 4: Database Persistence:** Basis data SQLite [`tkpi_nutrition.db`](tkpi_nutrition.db) berisi 1.300+ data uji lab TKPI Kemenkes RI dan produk ritel.
- [x] **Layer 5: Environment Variables:** Proteksi kredensial rahasia menggunakan [`.env.example`](.env.example) dan [`.gitignore`](.gitignore).
- [x] **Layer 6: Cloud-Native Deployment:** Siap di-deploy dengan container [Dockerfile](Dockerfile) ke **Google Cloud Run** maupun Streamlit Community Cloud.
- [x] **Layer 7: Monitoring & Alerting ke HP:** Modul [`alert_manager.py`](alert_manager.py) untuk mengirim notifikasi instan ke Telegram jika terjadi error server.

---

## 🚀 Cara Menjalankan Secara Lokal

1. **Install Dependensi:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup File Kredensial (.env):**
   Salin `.env.example` menjadi `.env` lalu masukkan API Key Google Gemini:
   ```env
   GEMINI_API_KEY=AIzaSy...
   ```

3. **Jalankan Unit Test:**
   ```bash
   python tests/test_nutrition.py
   ```

4. **Jalankan Aplikasi:**
   ```bash
   streamlit run app.py
   ```
   Aplikasi akan terbuka di browser pada alamat `http://localhost:8501`.

---

## ☁️ Deploy ke Google Cloud Run

Proyek ini telah dilengkapi dengan `Dockerfile` dan `.dockerignore` siap pakai untuk Google Cloud Run:

```bash
gcloud run deploy nutrisi-cerdas \
  --source . \
  --region asia-southeast2 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY="API_KEY_ANDA"
```

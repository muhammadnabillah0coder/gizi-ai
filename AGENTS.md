# Nutrisi Cerdas Engineering & AI Guidelines (Layer 2)

Proyek ini dibangun berdasarkan framework **Production Maturity Roadmap** (Bottom-Up Engineering) untuk platform **Nutrisi Cerdas: Precision Food & Lab Nutrition Intelligence**. Semua perubahan kode, baik oleh manusia maupun AI Assistant, wajib mematuhi aturan arsitektur berikut.

---

## 1. Arsitektur Inti (Clinical Verification Engine)
- **Zero-Token Deterministic Math:** Seluruh perhitungan kalori, makronutrien (protein, lemak, karbohidrat, serat), dan natrium **wajib** dihitung oleh kode lokal (`nutrition_engine.py`) berbasis data uji lab **TKPI Kemenkes RI** per 100g BDD.
- **AI Scope Boundary:** AI (Gemini Flash Vision/Text) **hanya bertugas** mengekstrak nama menu, komponen bahan, dan taksiran gramatur berdasarkan standar URT (Ukuran Rumah Tangga) porsi Indonesia. AI **dilarang keras** mengarang angka kalori dari nol guna mencegah halusinasi klinis.

## 2. Standar Keamanan & Secret Management (Layer 5)
- Jangan pernah melakukan *hardcode* API Key, token, atau kredensial ke dalam file kode (`.py`, `.html`, `.js`).
- Gunakan environment variable `GEMINI_API_KEY` dari file `.env`.
- File `.env` wajib dimasukkan ke dalam `.gitignore`.

## 3. Ketahanan & Pengujian (Layer 3)
- Setiap penambahan menu pangan ke database atau logika kalkulasi wajib memiliki unit test di folder `tests/`.
- Test runner wajib lolos sebelum deploy (`pytest` atau `python -m unittest`).

## 4. UI/UX Porsi Interaktif (Adaptive URT Slider)
- Pengguna awam tidak tahu berat gram makanan. UI Nutrisi Cerdas wajib menyediakan default porsi URT dengan slider penyesuaian porsi cepat:
  - 0.7x (Porsi Sedikit)
  - 1.0x (Porsi Normal Standar)
  - 1.3x (Porsi Kenyang/Banyak)
  - 1.5x (Porsi Jumbo)
- Penyesuaian slider porsi wajib menghitung ulang secara instan di sisi client/backend tanpa melakukan request API ulang ke AI.

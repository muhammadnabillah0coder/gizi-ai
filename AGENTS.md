# Nutrisi Cerdas Engineering & AI Guidelines (Layer 2)

Proyek ini dibangun berdasarkan framework **Production Maturity Roadmap** (Bottom-Up Engineering) untuk platform **Nutrisi Cerdas (`v4.2.0`)**. Semua perubahan kode wajib mematuhi aturan arsitektur berikut.

---

## 1. Arsitektur Inti (Clinical Verification Engine)
- **Zero-Token Deterministic Math:** Seluruh perhitungan kalori, makronutrien (protein, lemak, karbohidrat, serat), natrium, dan gula (`sugar_g` / Rambu GGL Kemenkes) **wajib** dihitung oleh kode lokal (`nutrition_engine.py`) berbasis data uji lab **TKPI Kemenkes RI** dan katalog ritel BPOM per 100g BDD.
- **AI Scope Boundary:** AI (`google-genai` / Gemini Flash Lite) **hanya bertugas** mengekstrak identitas menu, komponen bahan, kode barcode kemasan, dan taksiran gramatur URT Indonesia. AI **dilarang keras** mengarang kalori atau meloloskan input non-pangan/hewan ekstrem.
- **4-Layer Food Guardrails:** Seluruh jalur teks, foto, input manual, dan restore `.json` wajib melewati `food_guardrails.py` (anti non-pangan, anti takaran grosir mustahil, validasi fisika Atwater, dan batas harian 12.000 kkal / 25 menu).

## 2. Privasi, Keamanan & Seed Database Hygiene (Layer 4 & 5)
- Jangan pernah melakukan *hardcode* API Key, token Telegram, atau kredensial OAuth/DB di kode sumber.
- File seed `tkpi_nutrition.db` di Git wajib **100% bebas data pengguna & secret** (`users=0`, `meal_logs=0`, `app_meta=0`), diverifikasi dengan `python sanitize_seed_db.py --check`.
- Pengunjung belum login wajib diisolasi ke sesi tamu per-browser (`guest_<hex>`) dengan auto-migrasi ke akun baru saat pendaftaran/login.
- Autentikasi menggunakan PBKDF2-SHA256 bersalt, token sesi URL HMAC TTL 30 hari, serta OAuth anti-CSRF `state` sekali pakai.

## 3. UI/UX Porsi Interaktif & Unslop 60/30/10
- Antarmuka mengikuti standar `unslop` dan aturan warna **60/30/10** (kanvas netral hangat/gelap tenang, satu aksen kontras tinggi, bebas gradien dekoratif, emoji UI, *all-caps*, atau tanda seru).
- Slider porsi URT mendukung rentang **0.25x, 0.5x, 0.75x, 1.0x, 1.5x, hingga 2.0x** beserta checklist komponen piring yang dihitung ulang instan (0 token AI) dalam alur Preview tunggal anti-dobel.

## 4. Pengujian & CI/CD (Layer 3, 6 & 7)
- Seluruh perubahan wajib lolos `py_compile`, `python sanitize_seed_db.py --check`, dan `python -m unittest discover -s tests -v` (serta otomatis diverifikasi GitHub Actions `.github/workflows/ci.yml`).
- Kegagalan kritis koneksi Cloud DB (Supabase) atau API Gemini wajib diteruskan ke `alert_manager.py` dengan *cooldown* anti-spam 10 menit.

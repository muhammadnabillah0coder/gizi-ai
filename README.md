# Nutrisi Cerdas (`v4.6.0`): Precision Food & Lab Nutrition Intelligence

Aplikasi web pelacak kalori, makronutrien, **Kuis Rencana Gizi Personal 4 Langkah**, **Mode Puasa (Ramadan/Sunnah & IF 16:8)**, **Kartu Visual IG Story / WA Status 9:16**, **Paket Pro & Pembayaran QRIS (Mayar.id / Midtrans / Voucher)**, Konsultan **Tanya Gizi AI** kontekstual, dan Rambu GGL Kemenkes RI (Gula, Garam/Natrium, Lemak) berbasis **1.304 data laboratorium TKPI Kemenkes RI**, **45 produk kemasan ritel BPOM ber-barcode EAN-13**, serta **Open Food Facts / USDA**.

Dibangun dengan arsitektur **Bottom-Up Engineering (7-Layer Production Maturity Roadmap)**, **PWA siap pasang di HP**, auto-login **Browser Cookie + `localStorage` 30 hari per HP**, dual-backend **Supabase PostgreSQL + SQLite**, pertahanan 4-lapis *Food Guardrails*, dan antarmuka **Unslop 60/30/10**.

- Panduan deploy publik **Google Cloud Run Jakarta (`asia-southeast2`) + Custom Domain HTTPS + PWA**: [DEPLOY_PUBLIC_GUIDE.md](DEPLOY_PUBLIC_GUIDE.md)
- Panduan setup **Paket Pro & Pembayaran QRIS (Mayar.id / Midtrans / Voucher)**: [PAYMENT_QRIS_GUIDE.md](PAYMENT_QRIS_GUIDE.md)

---

## Arsitektur Inti

```text
               [ Input Pengguna ]
           /           |          \
   [ Kamera HP ]   [ Teks Bebas ]   [ Barcode EAN-13 / Foto Label ]
         |             |                   |
         v             v                   |
  +--------------------------+             |
  |  Gemini Vision & Parser  |             |
  |   (google-genai SDK +    |             |
  |    4-Layer Guardrails)   |             |
  +--------------------------+             |
               |                           |
               +-------------+-------------+
                             |
                             v
           +-----------------------------------+
           |    Clinical Verification Core     |
           |   (0-Token Deterministic Math)    |
           |  - TKPI Kemenkes RI (1.304 item)  |
           |  - 45 Produk Ritel BPOM (EAN-13)  |
           |  - Nutri-Grade & Rambu GGL        |
           +-----------------------------------+
                             |
                             v
           +-----------------------------------+
           |  Quiet Craft Analytics (Unslop)   |
           |  - Cincin Kalori SVG Terkalibrasi |
           |  - Grafik 7 Hari (Kalori/Protein) |
           |  - Hidrasi Adaptif & Tren BB      |
           +-----------------------------------+
```

---

## 7 Lapisan Kesiapan Produksi (`v4.2.0`)

- [x] **Layer 1 · Entry Point Terpadu:** [app.py](app.py) dengan antarmuka tenang *Unslop 60/30/10*, sesi tamu terisolasi (`guest_*`) + auto-migrasi ke akun baru, edit profil & ganti PIN, serta dukungan Login Google OAuth.
- [x] **Layer 2 · Engineering Rules:** [AGENTS.md](AGENTS.md) mengatur batas AI, *guardrails* pangan, higienitas seed DB, dan disiplin UI.
- [x] **Layer 3 · Automated Testing & CI:** Suite `tests/` (unit test nutrisi, auth, dual-backend, *food guardrails*, security hardening, `AppTest` UI smoke, dan v4.2 regression) berjalan otomatis di GitHub Actions [`.github/workflows/ci.yml`](.github/workflows/ci.yml).
- [x] **Layer 4 · Dual-Backend Database:** Permanen via **Supabase PostgreSQL (`pg8000` SSL pool)** dengan fallback otomatis ke SQLite [tkpi_nutrition.db](tkpi_nutrition.db) (seed Git dibersihkan lewat [sanitize_seed_db.py](sanitize_seed_db.py)).
- [x] **Layer 5 · Security & Secrets:** PBKDF2-SHA256 bersalt, sesi URL HMAC TTL 30 hari, anti-CSRF OAuth `state`, sanitasi CSV/HTML, dan pemisahan kredensial di [`.env.example`](.env.example).
- [x] **Layer 6 · Cloud-Native Deployment:** Live di Streamlit Community Cloud serta [Dockerfile](Dockerfile) non-root dengan XSRF aktif & `HEALTHCHECK` untuk Google Cloud Run.
- [x] **Layer 7 · Active Monitoring:** [alert_manager.py](alert_manager.py) terhubung ke error kritis DB Cloud & Gemini API dengan dukungan `st.secrets`, redaksi token, dan *cooldown* 10 menit anti-spam.

---

## Cara Menjalankan Secara Lokal

1. **Pasang Dependensi:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Konfigurasi Kredensial (`.env`):**
   Salin `.env.example` menjadi `.env`, lalu isi `GEMINI_API_KEY` (dan opsional `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).
3. **Verifikasi Kebersihan Seed DB & Jalankan Test:**
   ```bash
   python sanitize_seed_db.py --check
   python -m unittest discover -s tests -v
   ```
4. **Jalankan Aplikasi:**
   ```bash
   streamlit run app.py
   ```

# Panduan Publikasi Mandiri: Google Cloud Run (Jakarta), Domain Sendiri & PWA

Panduan ini memindahkan **Nutrisi Cerdas** dari subdomain gratis `.streamlit.app` (yang bisa tertidur bila sepi) ke **server mandiri berkecepatan tinggi di Jakarta (`asia-southeast2`)** lengkap dengan **domain sendiri (`.id` / `.com`)**, SSL HTTPS otomatis, dan dukungan **Install Aplikasi (PWA)** di HP Android & iPhone.

---

## 1. Kenapa Google Cloud Run + Supabase?
* **Lokasi Jakarta (`asia-southeast2`):** Akses jauh lebih responsif untuk pengguna Indonesia (latensi rendah).
* **Hemat Biaya (*Pay-per-use* + Free Tier):** Cloud Run memiliki kuota gratis bulanan (*always free tier* hingga ~2 juta request & 180.000 vCPU-detik/bulan). Pada trafik awal ratusan pengguna harian, biaya biasanya berkisar **Rp0 – Rp50.000/bulan**.
* **Bebas Layar Tidur Streamlit Cloud:** Tidak ada halaman *"Zzz This app has gone to sleep"*; cold-start container hanya ~2–4 detik (atau 0 detik jika nanti mengatur `-MinInstances 1` saat pengguna sudah ribuan).
* **PWA & Cookie Stabil:** Berjalan langsung di domain utama Anda (bukan dibungkus iframe), sehingga tombol **Install / Tambahkan ke Layar Utama** dan **auto-login cookie 30 hari** bekerja optimal.

---

## 2. Langkah Deploy 1 Perintah (Windows PowerShell)

1. Pasang [Google Cloud CLI (`gcloud`)](https://cloud.google.com/sdk/docs/install) dan login:
   ```powershell
   gcloud auth login
   ```
2. Aktifkan API Cloud Run & Cloud Build pada proyek GCP Anda (sekali saja):
   ```powershell
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com
   ```
3. Setel kredensial di sesi terminal (tidak disimpan di kode), lalu jalankan skrip deploy:
   ```powershell
   $env:GEMINI_API_KEY = "<GEMINI_API_KEY_ANDA>"
   $env:DATABASE_URL = "postgresql://postgres.<ref>:<pass>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
   $env:SESSION_SECRET = "ganti-dengan-string-acak-minimal-32-karakter"
   # Opsional jika Google Login & Alert Telegram dipakai:
   # $env:GOOGLE_CLIENT_ID = "..."
   # $env:GOOGLE_CLIENT_SECRET = "..."
   # $env:TELEGRAM_BOT_TOKEN = "..."
   # $env:TELEGRAM_CHAT_ID = "..."

   .\deploy_cloud_run.ps1 -ProjectId "id-proyek-gcp-anda"
   ```
4. Setelah selesai, Anda langsung mendapatkan URL HTTPS aktif `https://nutrisi-cerdas-xxxxx-et.a.run.app`.

> **Tip Keamanan Produksi:** Setelah nyaman, pindahkan secret ke **Google Secret Manager** agar kredensial tidak terlihat di konfigurasi env Cloud Run.

---

## 3. Menghubungkan Domain Sendiri (Misal `nutrisicerdas.id`)

1. Beli domain di registrar pilihan (Niagahoster / Rumahweb / DomaiNesia / Cloudflare, kisaran Rp150.000–Rp250.000/tahun).
2. Verifikasi kepemilikan domain di [Google Search Console](https://search.google.com/search-console) memakai TXT record DNS.
3. Buat pemetaan domain di Cloud Run:
   ```powershell
   gcloud beta run domain-mappings create `
     --service nutrisi-cerdas `
     --domain nutrisicerdas.id `
     --region asia-southeast2
   ```
4. Salin record **A / AAAA / CNAME** yang diberikan Google ke panel DNS domain Anda (Cloudflare / registrar). Dalam 15–30 menit, sertifikat **SSL HTTPS otomatis** aktif di `https://nutrisicerdas.id`.
5. Tambahkan `https://nutrisicerdas.id` ke **Authorized redirect URIs** pada Google Cloud Console OAuth 2.0 agar tombol **Masuk dengan Google** bekerja di domain baru.

---

## 4. Verifikasi Install PWA di HP
Proyek ini sudah menyertakan `static/manifest.json`, ikon `192×192` & `512×512`, `enableStaticServing = true` di `.streamlit/config.toml`, dan injeksi tag `<link rel="manifest">` otomatis di `session_cookie.py`:
* **Android (Chrome):** Buka `https://nutrisicerdas.id` -> menu titik tiga -> **Tambahkan ke layar utama / Install aplikasi**.
* **iPhone (Safari):** Buka `https://nutrisicerdas.id` -> tombol **Bagikan (Share)** -> **Tambah ke Layar Utama (*Add to Home Screen*)**.
* Ikon **Nutrisi Cerdas** langsung tampil di layar utama HP dengan mode layar penuh (`standalone`) dan sesi akun tetap login otomatis selama 30 hari.

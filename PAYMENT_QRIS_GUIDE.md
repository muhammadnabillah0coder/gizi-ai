# Panduan Setup Paket Pro & Pembayaran QRIS (Mayar.id / Midtrans)

Nutrisi Cerdas (`v4.6.0`) mendukung **3 mode pembayaran QRIS** sehingga Anda bisa langsung menerima pembayaran Pro mulai hari ini (bahkan saat masih di Streamlit Cloud) maupun otomatis 100% lewat webhook begitu pengguna makin ramai.

---

## Struktur Paket Resmi (Dapat Diubah di `payment_gateway.py`)
| Kode Paket | Nama | Harga | Masa Aktif | Fasilitas Tambahan di Atas Gratis Permanen |
| :--- | :--- | :--- | :--- | :--- |
| `PRO_7D` | **Pass Pro 7 Hari** | `Rp9.000` | 7 hari | Scan foto AI & Tanya Gizi AI tanpa batas (pintu masuk *low-friction*) |
| `PRO_30D` | **Pro Bulanan** | `Rp19.000` | 30 hari | Scan foto AI & Tanya Gizi AI tanpa batas (*Paling Populer*) |
| `PRO_365D` | **Pro Tahunan** | `Rp149.000` | 365 hari | Scan foto AI & Tanya Gizi AI tanpa batas (hemat ~35%) |

> **Aturan *Stacking* Adil:** Jika pengguna Pro memperpanjang sebelum masa aktifnya habis, hari baru otomatis ditambahkan di belakang tanggal kedaluwarsa lama — tidak hangus.

---

## Pilihan 1 (Tercepat Hari Ini — 5 Menit Aktif di Streamlit Cloud): Mode Tautan QRIS / WA + Kode Voucher Pro
Cocok saat fase **100 pengguna pertama** sebelum menjalankan server webhook terpisah:
1. Buat akun di [Mayar.id](https://mayar.id) (cukup KTP + rekening bank/e-wallet Indonesia, langsung dapat QRIS).
2. Buat 3 **Payment Link** (`Rp9.000`, `Rp19.000`, `Rp149.000`) lalu tempel di Streamlit Secrets / `.env`:
   ```toml
   MAYAR_CHECKOUT_URL_7D = "https://mayar.id/..."
   MAYAR_CHECKOUT_URL_30D = "https://mayar.id/..."
   MAYAR_CHECKOUT_URL_365D = "https://mayar.id/..."
   PRO_ADMIN_WA = "6281234567890"
   ```
3. Begitu ada pembayaran masuk, buka **Sidebar -> Kelola Paket Pro & Voucher QRIS (Admin)** di Nutrisi Cerdas:
   - Klik **Tandai Lunas & Aktifkan Pro** pada nomor order yang masuk, **atau**
   - Klik **Buat kode voucher Pro** (`NCPRO-XXXX-XXXX`) lalu kirimkan ke pembeli agar mereka bisa menukarnya sendiri di menu **Paket Pro**.

---

## Pilihan 2 (Otomatis Penuh via API): Mayar.id API + Webhook
1. Ambil **API Key** dan atur **Webhook Token** di dashboard Mayar.id.
2. Pasang di environment server (Cloud Run / VPS):
   ```powershell
   $env:MAYAR_API_KEY = "<MAYAR_API_KEY_ANDA>"
   $env:MAYAR_WEBHOOK_TOKEN = "<TOKEN_ACAK_MIN_32_KARAKTER>"
   $env:MAYAR_IS_SANDBOX = "false"
   ```
3. Arahkan URL Webhook Mayar ke layanan FastAPI (`whatsapp_bot.py`):
   `https://<domain-api-anda>/webhook/mayar` dengan header `x-callback-token` sesuai `MAYAR_WEBHOOK_TOKEN`.
4. Begitu QRIS dibayar, server otomatis memverifikasi token & nominal lalu mengaktifkan Paket Pro (idempoten, aman dari webhook ganda) dan mengirim notifikasi ke Telegram Admin.

---

## Pilihan 3 (Alternatif Enterprise): Midtrans Snap QRIS + Verifikasi SHA-512
1. Daftar di [Midtrans](https://midtrans.com) -> salin **Server Key** (mulai dengan Sandbox `SB-Mid-server-...` untuk uji coba).
2. Setel environment variable:
   ```powershell
   $env:MIDTRANS_SERVER_KEY = "<MIDTRANS_SERVER_KEY_ANDA>"
   $env:MIDTRANS_IS_SANDBOX = "true"   # ubah ke "false" saat live
   ```
3. Pada dashboard Midtrans -> **Settings -> Configuration -> Payment Notification URL**, masukkan:
   `https://<domain-api-anda>/webhook/midtrans`
4. Endpoint otomatis memverifikasi `SHA512(order_id + status_code + gross_amount + server_key)` secara *constant-time* sebelum mengaktifkan Pro.

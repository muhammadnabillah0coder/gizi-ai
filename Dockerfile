# -----------------------------------------------------------------------------
# Dockerfile untuk Nutrisi Cerdas di Google Cloud Run
# -----------------------------------------------------------------------------
FROM python:3.11-slim

# Mencegah Python membuat file .pyc dan mematikan buffer agar log terbaca di GCP
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

WORKDIR /app

# Install paket sistem yang diperlukan
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependensi Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode proyek & basis data SQLite TKPI
COPY . .

# Expose port default Cloud Run
EXPOSE 8080

# Jalankan Streamlit dengan bind ke 0.0.0.0 dan port dinamis dari Cloud Run ($PORT)
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false --server.headless=true"]

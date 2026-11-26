#!/usr/bin/env bash
# Deploy 1-perintah Nutrisi Cerdas ke Google Cloud Run (Region Jakarta asia-southeast2)
# Penggunaan:
#   export GEMINI_API_KEY="AIza..."
#   export DATABASE_URL="postgresql://..."
#   ./deploy_cloud_run.sh <GCP_PROJECT_ID> [SERVICE_NAME] [REGION]

set -euo pipefail

PROJECT_ID="${1:?Harap isi GCP_PROJECT_ID sebagai argumen pertama}"
SERVICE_NAME="${2:-nutrisi-cerdas}"
REGION="${3:-asia-southeast2}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-5}"

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
  echo "Error: GEMINI_API_KEY belum disetel di environment." >&2
  exit 1
fi

echo "[1/4] Memverifikasi kebersihan seed tkpi_nutrition.db..."
python3 sanitize_seed_db.py --check

echo "[2/4] Menyusun environment variables produksi..."
ENV_VARS="GEMINI_API_KEY=${GEMINI_API_KEY}"
for key in DATABASE_URL SESSION_SECRET GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID GEMINI_MODEL; do
  val="${!key:-}"
  if [[ -n "$val" ]]; then
    ENV_VARS="${ENV_VARS},${key}=${val}"
  fi
done

echo "[3/4] Deploying ${SERVICE_NAME} ke Cloud Run (${REGION})..."
gcloud config set project "$PROJECT_ID"
gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --min-instances "$MIN_INSTANCES" \
  --max-instances "$MAX_INSTANCES" \
  --session-affinity \
  --set-env-vars "$ENV_VARS"

echo "[4/4] Selesai! Sambungkan domain sendiri dengan:"
echo "  gcloud beta run domain-mappings create --service ${SERVICE_NAME} --domain nutrisicerdas.id --region ${REGION}"

"""
Layer 7: Monitoring & Alerting Helper
Mengirimkan notifikasi error instan ke HP (Telegram Bot) saat terjadi unhandled exception / API failure.
"""

import html
import os
import re
import requests


def _redact_telegram_secrets(text: str, bot_token: str) -> str:
    clean = str(text or "")
    if bot_token:
        clean = clean.replace(bot_token, "[REDACTED]")
    return re.sub(r"/bot[^/\s]+", "/bot[REDACTED]", clean)


def send_alert_to_phone(error_message: str, context: str = "General"):
    """
    Mengirim pesan alert singkat ke Telegram HP pengembang.
    Hanya berjalan jika TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID disetel di .env
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        # Jika belum dikonfigurasi, cetak ke log konsol saja
        print(f"[LOCAL ERROR LOG - {context}]: {error_message}")
        return False

    safe_ctx = html.escape(str(context or "General")[:100])
    safe_err = html.escape(_redact_telegram_secrets(str(error_message or "")[:200], bot_token))
    text = (
        f"🚨 <b>Nutrisi Cerdas Production Alert</b>\n"
        f"📌 <b>Context:</b> {safe_ctx}\n"
        f"⚠️ <b>Error:</b> <code>{safe_err}</code>\n"
        f"🕒 <b>Timestamp:</b> Segera periksa server log."
    )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        resp = requests.post(url, json=payload, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        safe_exc = _redact_telegram_secrets(str(e), bot_token)
        print(f"Gagal mengirim alert ke Telegram ({type(e).__name__}): {safe_exc}")
        return False

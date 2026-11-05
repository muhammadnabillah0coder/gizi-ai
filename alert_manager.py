"""
Layer 7: Monitoring & Alerting Helper
Mengirimkan notifikasi error instan ke HP (Telegram Bot) saat terjadi unhandled exception / API failure.
"""

import os
import requests
import traceback

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
        
    text = (
        f"🚨 *Gizi.AI Production Alert*\n"
        f"📌 *Context:* {context}\n"
        f"⚠️ *Error:* `{error_message[:200]}`\n"
        f"🕒 *Timestamp:* Segera periksa server log."
    )
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print(f"Gagal mengirim alert ke Telegram: {e}")
        return False

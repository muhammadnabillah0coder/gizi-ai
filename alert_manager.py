"""
Layer 7: Monitoring & Alerting Helper
Mengirimkan notifikasi error instan ke HP (Telegram Bot) saat terjadi kegagalan kritis server/DB/AI,
dilengkapi pembacaan st.secrets, redaksi token rahasia, HTML escaping, dan cooldown anti-spam.
"""

import html
import os
import re
import threading
import time
import requests

_ALERT_LOCK = threading.Lock()
_LAST_ALERT_SENT: dict[str, float] = {}
ALERT_COOLDOWN_SECONDS = 600


def _redact_telegram_secrets(text: str, bot_token: str) -> str:
    clean = str(text or "")
    if bot_token:
        clean = clean.replace(bot_token, "[REDACTED]")
    return re.sub(r"/bot[^/\s]+", "/bot[REDACTED]", clean)


def _get_telegram_credentials() -> tuple[str, str]:
    """Mengambil TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID dari environment atau Streamlit Secrets."""
    bot_token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if not bot_token or not chat_id:
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if not bot_token and "TELEGRAM_BOT_TOKEN" in st.secrets:
                    bot_token = str(st.secrets["TELEGRAM_BOT_TOKEN"]).strip()
                if not chat_id and "TELEGRAM_CHAT_ID" in st.secrets:
                    chat_id = str(st.secrets["TELEGRAM_CHAT_ID"]).strip()
        except Exception:
            pass
    return bot_token, chat_id


def reset_alert_cooldown():
    """Mengosongkan cache cooldown alert (berguna untuk pengujian unit)."""
    with _ALERT_LOCK:
        _LAST_ALERT_SENT.clear()


def send_alert_to_phone(
    error_message: str,
    context: str = "General",
    cooldown_seconds: int = ALERT_COOLDOWN_SECONDS,
    force: bool = False,
) -> bool:
    """
    Mengirim pesan alert singkat ke Telegram HP pengembang.
    Hanya berjalan jika TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID disetel di .env / st.secrets.
    Menggunakan cooldown per-konteks agar error berulang tidak membanjiri Telegram.
    """
    bot_token, chat_id = _get_telegram_credentials()

    if not bot_token or not chat_id:
        print(f"[LOCAL ERROR LOG - {context}]: {error_message}")
        return False

    ctx_key = str(context or "General").strip().lower()[:100]
    now_mono = time.monotonic()
    if not force and cooldown_seconds > 0:
        with _ALERT_LOCK:
            last_ts = _LAST_ALERT_SENT.get(ctx_key)
            if last_ts is not None and (now_mono - last_ts) < cooldown_seconds:
                return False
            _LAST_ALERT_SENT[ctx_key] = now_mono

    safe_ctx = html.escape(str(context or "General")[:100])
    safe_err = html.escape(_redact_telegram_secrets(str(error_message or "")[:240], bot_token))
    text = (
        f"<b>Nutrisi Cerdas Production Alert</b>\n"
        f"<b>Context:</b> {safe_ctx}\n"
        f"<b>Error:</b> <code>{safe_err}</code>\n"
        f"<b>Status:</b> Segera periksa server log."
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

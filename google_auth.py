"""
Google OAuth 2.0 Helper untuk Platform Nutrisi Cerdas
Menghandle pembuatan URL login Google dan pertukaran auth code menjadi data profil user (email, nama, foto).
"""

import hashlib
import hmac
import os
import secrets
import threading
import time
import urllib.parse
import requests

_MODULE_MTIME = round(os.path.getmtime(__file__), 6) if os.path.exists(__file__) else 0.0
_OAUTH_STATE_LOCK = threading.Lock()
_CONSUMED_OAUTH_STATES: dict[str, int] = {}
_FALLBACK_STATE_SECRET = secrets.token_bytes(32)


def _get_oauth_state_secret() -> bytes:
    """Mengambil kunci penandatangan HMAC untuk parameter OAuth state tanpa hardcode."""
    try:
        from db_history import _get_session_secret_key
        return _get_session_secret_key()
    except Exception:
        _, sec = get_credentials()
        if sec:
            return hashlib.sha256(f"nutrisi_cerdas_oauth::{sec}".encode("utf-8")).digest()
        return _FALLBACK_STATE_SECRET


def create_oauth_state(ttl_seconds: int = 600, browser_binding: str = "") -> str:
    """Membuat parameter state bertanda tangan HMAC dengan pengikatan sesi browser (anti-Login CSRF)."""
    exp_ts = int(time.time()) + int(ttl_seconds)
    nonce = secrets.token_hex(12)
    b_tag = hashlib.sha256(str(browser_binding or "").encode("utf-8")).hexdigest()[:12] if browser_binding else "unbound"
    key = _get_oauth_state_secret()
    sig = hmac.new(key, f"oauth|{exp_ts}|{b_tag}|{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{exp_ts}.{nonce}.{sig}"


def verify_oauth_state(
    state: str,
    max_ttl_seconds: int = 600,
    consume: bool = True,
    browser_binding: str = "",
    require_binding: bool = False,
) -> bool:
    """Memvalidasi integritas, masa berlaku, pengikatan browser, dan replay nonce DB untuk state OAuth."""
    raw = str(state or "").strip()
    parts = raw.split(".")
    if len(parts) != 3:
        return False
    exp_str, nonce, sig = parts
    if not exp_str.isdigit() or len(nonce) < 8 or len(sig) != 24:
        return False
    if require_binding and not str(browser_binding or "").strip():
        return False
    exp_ts = int(exp_str)
    now_ts = int(time.time())
    if exp_ts <= now_ts or exp_ts > (now_ts + max_ttl_seconds + 60):
        return False
    b_tag = hashlib.sha256(str(browser_binding or "").encode("utf-8")).hexdigest()[:12] if browser_binding else "unbound"
    key = _get_oauth_state_secret()
    expected = hmac.new(key, f"oauth|{exp_ts}|{b_tag}|{nonce}".encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(expected, sig):
        return False

    with _OAUTH_STATE_LOCK:
        expired_keys = [k for k, ts in _CONSUMED_OAUTH_STATES.items() if ts <= now_ts]
        for k in expired_keys:
            _CONSUMED_OAUTH_STATES.pop(k, None)
        if nonce in _CONSUMED_OAUTH_STATES:
            return False
        if consume:
            try:
                from db_history import consume_oauth_nonce_db
                if not consume_oauth_nonce_db(nonce, exp_ts):
                    return False
            except Exception:
                pass
            _CONSUMED_OAUTH_STATES[nonce] = exp_ts
    return True


def get_credentials():
    """Mengambil credentials dari environment atau st.secrets tanpa hardcode."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    
    try:
        import streamlit as st
        if not client_id and hasattr(st, "secrets") and "GOOGLE_CLIENT_ID" in st.secrets:
            client_id = st.secrets["GOOGLE_CLIENT_ID"]
        if not client_secret and hasattr(st, "secrets") and "GOOGLE_CLIENT_SECRET" in st.secrets:
            client_secret = st.secrets["GOOGLE_CLIENT_SECRET"]
    except:
        pass
        
    return client_id, client_secret

def get_google_auth_url(redirect_uri: str, state: str = None, browser_binding: str = "") -> str:
    """Membuat URL resmi Sign-In with Google lengkap dengan parameter state anti-CSRF."""
    client_id, _ = get_credentials()
    if not client_id:
        return "#"
        
    base_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state or create_oauth_state(browser_binding=browser_binding),
    }
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def exchange_code_for_user(code: str, redirect_uri: str):
    """
    Menukar authorization code dari Google menjadi data profil pengguna (email, name, picture).
    """
    client_id, client_secret = get_credentials()
    if not client_id or not client_secret:
        return None, "CLIENT_ID atau CLIENT_SECRET belum diset di Streamlit Secrets"
        
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    
    try:
        res = requests.post(token_url, data=data, timeout=10)
        res_json = res.json()
        
        access_token = res_json.get("access_token")
        if not access_token:
            err_msg = res_json.get("error_description") or res_json.get("error") or str(res_json)
            return None, f"Google Token Error: {err_msg}"
            
        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        headers = {"Authorization": f"Bearer {access_token}"}
        user_res = requests.get(userinfo_url, headers=headers, timeout=10)
        user_info = user_res.json()
        
        email = (user_info.get("email") or "").strip().lower()
        verified = bool(user_info.get("verified_email", False))
        if not email:
            return None, "Google tidak mengembalikan alamat email akun."
        if not verified:
            return None, "Email Google Anda belum terverifikasi."

        return {
            "email": email,
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            "verified_email": True
        }, None
    except Exception as e:
        return None, f"Exception: {str(e)}"

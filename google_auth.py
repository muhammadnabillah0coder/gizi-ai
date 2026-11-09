"""
Google OAuth 2.0 Helper untuk Streamlit Gizi.AI
Menghandle pembuatan URL login Google dan pertukaran auth code menjadi data profil user (email, nama, foto).
"""

import os
import urllib.parse
import requests

import os
import urllib.parse
import requests

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

def get_google_auth_url(redirect_uri: str) -> str:
    """Membuat URL resmi Sign-In with Google."""
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
        "prompt": "select_account"
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
        
        return {
            "email": user_info.get("email"),
            "name": user_info.get("name"),
            "picture": user_info.get("picture"),
            "verified_email": user_info.get("verified_email", False)
        }, None
    except Exception as e:
        return None, f"Exception: {str(e)}"

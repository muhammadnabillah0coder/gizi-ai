"""
Persistent Per-Device Browser Cookie + localStorage Session Bridge (Nutrisi Cerdas v4.3.0)
Memanfaatkan API native Streamlit >=1.50 (st.context.cookies + st.components.v2.component same-origin)
tanpa library pihak ketiga dan tanpa pernah menyimpan PIN/password polos di perangkat pengguna.
Hanya menyimpan token HMAC-SHA256 bertanda tangan (TTL 30 hari) untuk auto-login instan di tiap HP.
"""

import json
import os
import re
import streamlit as st

_MODULE_MTIME = round(os.path.getmtime(__file__), 6) if os.path.exists(__file__) else 0.0

COOKIE_UID = "nc_uid"
COOKIE_SIG = "nc_sig"
COOKIE_AUTH = "nc_auth"
COOKIE_GUEST = "nc_guest"
AUTH_COOKIE_MAX_AGE = 30 * 86400   # 30 hari
GUEST_COOKIE_MAX_AGE = 7 * 86400   # 7 hari

_GUEST_ID_RE = re.compile(r"^guest_[0-9a-f]{12}$")

# Static trusted JS (TIDAK pernah menyisipkan input user ke string JS; semua data lewat parameter `data`)
_COOKIE_BRIDGE_JS = """
const LS_KEY = "nc_session_v1";

function cookieAttrs(maxAge) {
    const isHttps = window.location.protocol === "https:";
    let isCrossSite = false;
    try {
        isCrossSite = window.self !== window.top && window.top.location.origin !== window.location.origin;
    } catch (_e) {
        isCrossSite = true;
    }
    const sameSite = (isHttps && isCrossSite) ? "None" : "Lax";
    const sec = isHttps ? "; Secure" : "";
    return `; Path=/; Max-Age=${maxAge}; SameSite=${sameSite}${sec}`;
}

function getCookie(name) {
    const raw = document.cookie || "";
    const parts = raw.split("; ");
    for (let i = 0; i < parts.length; i++) {
        const idx = parts[i].indexOf("=");
        if (idx > 0 && parts[i].slice(0, idx) === name) {
            try {
                return decodeURIComponent(parts[i].slice(idx + 1));
            } catch (_e) {
                return parts[i].slice(idx + 1);
            }
        }
    }
    return "";
}

function setCookie(name, val, maxAge) {
    document.cookie = `${name}=${encodeURIComponent(String(val || ""))}${cookieAttrs(maxAge)}`;
}

function clearCookie(name) {
    document.cookie = `${name}=${cookieAttrs(0)}`;
}

function injectPwaHead() {
    if (window.__ncPwaHeadInjected || !document.head) {
        return;
    }
    window.__ncPwaHeadInjected = true;
    try {
        if (!document.querySelector('link[rel="manifest"]')) {
            const link = document.createElement("link");
            link.rel = "manifest";
            link.href = "/app/static/manifest.json";
            document.head.appendChild(link);
        }
        const metas = [
            ["theme-color", "#15803D"],
            ["mobile-web-app-capable", "yes"],
            ["apple-mobile-web-app-capable", "yes"],
            ["apple-mobile-web-app-title", "Nutrisi Cerdas"],
            ["apple-mobile-web-app-status-bar-style", "default"]
        ];
        for (let i = 0; i < metas.length; i++) {
            const [mName, mContent] = metas[i];
            if (!document.querySelector(`meta[name="${mName}"]`)) {
                const m = document.createElement("meta");
                m.name = mName;
                m.content = mContent;
                document.head.appendChild(m);
            }
        }
    } catch (_e) {}
}

export default function(component) {
    injectPwaHead();
    const { data, setTriggerValue } = component;
    if (!data || typeof data !== "object") {
        return;
    }
    const action = data.action || "";

    if (action === "clear") {
        clearCookie("nc_uid");
        clearCookie("nc_sig");
        clearCookie("nc_auth");
        clearCookie("nc_guest");
        try {
            window.localStorage.removeItem(LS_KEY);
        } catch (_e) {}
        window.__ncRestoredSig = null;
        return;
    }

    if (action === "set_auth" && data.u && data.s) {
        const maxAge = Number(data.max_age || 2592000);
        const authVal = String(data.auth || "local");
        if (getCookie("nc_uid") !== data.u || getCookie("nc_sig") !== data.s) {
            setCookie("nc_uid", data.u, maxAge);
            setCookie("nc_sig", data.s, maxAge);
            setCookie("nc_auth", authVal, maxAge);
        }
        if (getCookie("nc_guest")) {
            clearCookie("nc_guest");
        }
        try {
            window.localStorage.setItem(LS_KEY, JSON.stringify({ u: data.u, s: data.s, auth: authVal }));
        } catch (_e) {}
        window.__ncRestoredSig = data.s;
        return;
    }

    if (action === "set_guest") {
        if (data.try_restore) {
            let storedRaw = "";
            try {
                storedRaw = window.localStorage.getItem(LS_KEY) || "";
            } catch (_e) {}
            if (storedRaw) {
                try {
                    const parsed = JSON.parse(storedRaw);
                    if (parsed && parsed.u && parsed.s && window.__ncRestoredSig !== parsed.s) {
                        window.__ncRestoredSig = parsed.s;
                        const maxAge = 2592000;
                        setCookie("nc_uid", parsed.u, maxAge);
                        setCookie("nc_sig", parsed.s, maxAge);
                        setCookie("nc_auth", parsed.auth || "local", maxAge);
                        setTriggerValue("restored", JSON.stringify({
                            u: String(parsed.u),
                            s: String(parsed.s),
                            auth: String(parsed.auth || "local")
                        }));
                        return;
                    }
                } catch (_e) {}
            }
        }
        if (data.g) {
            const gMaxAge = Number(data.max_age || 604800);
            if (getCookie("nc_guest") !== data.g) {
                setCookie("nc_guest", data.g, gMaxAge);
            }
        }
    }
}
"""

_COOKIE_BRIDGE_CSS = ":host { display: none !important; height: 0 !important; margin: 0 !important; padding: 0 !important; }"


@st.cache_resource(show_spinner=False)
def _get_cookie_bridge_component():
    """Mendaftarkan komponen v2 sekali per server process (tanpa duplikasi registrasi)."""
    if not hasattr(st, "components") or not hasattr(st.components, "v2"):
        return None
    return st.components.v2.component(
        "nc_session_cookie_bridge",
        css=_COOKIE_BRIDGE_CSS,
        js=_COOKIE_BRIDGE_JS,
    )


def read_browser_cookies() -> dict:
    """Membaca HTTP cookies browser secara aman dari st.context.cookies (0ms pada setiap request)."""
    try:
        if hasattr(st, "context") and hasattr(st.context, "cookies"):
            return {str(k): str(v) for k, v in st.context.cookies.items()}
    except Exception:
        pass
    return {}


def extract_valid_guest_cookie(cookies: dict) -> str:
    """Mengambil ID sesi tamu dari cookie hanya jika cocok dengan format aman guest_<12hex>."""
    raw = str((cookies or {}).get(COOKIE_GUEST) or "").strip().lower()
    if _GUEST_ID_RE.fullmatch(raw):
        return raw
    return ""


def parse_restored_session_payload(raw_payload) -> tuple[str, str, str] | None:
    """Mem-parsing payload pemulihan sesi dari localStorage fallback menjadi (uid, sig, auth)."""
    if not raw_payload:
        return None
    try:
        data = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
        if not isinstance(data, dict):
            return None
        uid = str(data.get("u") or "").strip().lower()
        sig = str(data.get("s") or "").strip()
        auth = str(data.get("auth") or "local").strip().lower()
        if auth not in {"local", "google"}:
            auth = "local"
        if uid and sig:
            return uid, sig, auth
    except Exception:
        pass
    return None


def build_cookie_bridge_payload(
    *,
    clear: bool = False,
    is_guest: bool = True,
    user_id: str = "",
    session_token: str = "",
    auth_provider: str = "local",
    try_restore: bool = True,
) -> dict:
    """Menyusun instruksi data terstruktur yang aman untuk dikirim ke komponen cookie bridge."""
    if clear:
        return {"action": "clear"}
    if not is_guest and user_id and session_token:
        return {
            "action": "set_auth",
            "u": str(user_id).strip().lower(),
            "s": str(session_token).strip(),
            "auth": auth_provider if auth_provider in {"local", "google"} else "local",
            "max_age": AUTH_COOKIE_MAX_AGE,
        }
    return {
        "action": "set_guest",
        "g": str(user_id).strip().lower() if _GUEST_ID_RE.fullmatch(str(user_id or "").strip().lower()) else "",
        "try_restore": bool(try_restore),
        "max_age": GUEST_COOKIE_MAX_AGE,
    }


def mount_session_cookie_bridge(payload: dict) -> tuple[str, str, str] | None:
    """Memasang bridge cookie/localStorage tak terlihat dan mengembalikan payload pemulihan jika ada."""
    try:
        comp = _get_cookie_bridge_component()
        if comp is None:
            return None
        res = comp(data=payload, key="nc_cookie_bridge", on_restored_change=lambda: None)
        restored_raw = getattr(res, "restored", None) if res is not None else None
        return parse_restored_session_payload(restored_raw)
    except Exception:
        return None

"""
Modul Gateway Pembayaran QRIS & Langganan Paket Pro untuk Nutrisi Cerdas (v4.6.0).
Mendukung 3 jalur bersih tanpa mengunci kredensial di kode:
1. Mayar.id Headless API (QRIS / E-Wallet / VA, registrasi perorangan KTP) via MAYAR_API_KEY
2. Midtrans Snap API (QRIS / GoPay / ShopeePay / VA) via MIDTRANS_SERVER_KEY + verifikasi SHA-512 resmi
3. Fallback QRIS Link Statis / Konfirmasi WhatsApp + Voucher Aktivasi Pro (langsung jalan di Streamlit Cloud)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import urllib.parse
import requests

import db_history

try:
    import streamlit as st
except Exception:
    st = None

try:
    from alert_manager import send_system_alert
except Exception:
    send_system_alert = None


PRO_PLANS: dict[str, dict] = {
    "PRO_7D": {
        "code": "PRO_7D",
        "name": "Pass Pro 7 Hari",
        "price_label": "Rp9.000",
        "amount_idr": 9000,
        "days": 7,
        "badge": "Uji Coba Hemat",
        "desc": "Scan foto AI & Tanya Gizi AI tanpa batas selama 7 hari penuh.",
    },
    "PRO_30D": {
        "code": "PRO_30D",
        "name": "Pro Bulanan",
        "price_label": "Rp19.000",
        "amount_idr": 19000,
        "days": 30,
        "badge": "Paling Populer",
        "desc": "Seharga 1 gelas kopi: scan foto AI & Tanya Gizi AI tanpa batas 30 hari.",
    },
    "PRO_365D": {
        "code": "PRO_365D",
        "name": "Pro Tahunan",
        "price_label": "Rp149.000",
        "amount_idr": 149000,
        "days": 365,
        "badge": "Hemat 35%",
        "desc": "Perlindungan penuh sepanjang tahun (~Rp12.400/bulan) tanpa batas harian.",
    },
}

_ORDER_ID_RE = re.compile(r"NC-[A-Z0-9_]+-\d{8}-[A-Z0-9]{4,12}")


def _get_cfg(key: str, default: str = "") -> str:
    val = os.environ.get(key, "")
    if val:
        return str(val).strip()
    if st is not None:
        try:
            if hasattr(st, "secrets") and key in st.secrets:
                return str(st.secrets[key]).strip()
        except Exception:
            pass
    return default


def _is_truthy(val: str) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on", "sandbox"}


def get_payment_gateway_status() -> dict:
    """Melaporkan jalur pembayaran QRIS yang aktif berdasarkan environment variable / Secrets."""
    mayar_key = _get_cfg("MAYAR_API_KEY")
    midtrans_key = _get_cfg("MIDTRANS_SERVER_KEY")
    static_30 = _get_cfg("MAYAR_CHECKOUT_URL_30D")
    admin_wa = _get_cfg("PRO_ADMIN_WA")

    if mayar_key:
        mode = "mayar_api"
        label = "Mayar.id QRIS API"
        sandbox = _is_truthy(_get_cfg("MAYAR_IS_SANDBOX"))
    elif midtrans_key:
        mode = "midtrans_snap"
        label = "Midtrans Snap QRIS"
        sandbox = _is_truthy(_get_cfg("MIDTRANS_IS_SANDBOX")) or midtrans_key.startswith("SB-")
    elif static_30:
        mode = "mayar_link"
        label = "Tautan QRIS Mayar"
        sandbox = False
    else:
        mode = "qris_manual_voucher"
        label = "QRIS & Kode Aktivasi Pro"
        sandbox = False

    return {
        "mode": mode,
        "label": label,
        "sandbox": sandbox,
        "has_admin_wa": bool(admin_wa),
        "admin_wa": admin_wa,
    }


def _normalize_wa_number(raw_wa: str) -> str:
    digits = "".join(ch for ch in str(raw_wa or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits


def build_manual_wa_confirm_url(order: dict, display_name: str = "") -> str:
    """Menyusun tautan WhatsApp konfirmasi order QRIS manual jika PRO_ADMIN_WA disetel."""
    wa_num = _normalize_wa_number(_get_cfg("PRO_ADMIN_WA"))
    if not wa_num:
        return ""
    plan = PRO_PLANS.get(order.get("plan_code", "PRO_30D"), PRO_PLANS["PRO_30D"])
    msg = (
        f"Halo Admin Nutrisi Cerdas, saya ingin aktivasi {plan['name']} ({plan['price_label']} via QRIS).\n"
        f"No. Order: {order['order_id']}\n"
        f"Akun: {order['user_id']} ({display_name or order['user_id']})"
    )
    return f"https://wa.me/{wa_num}?text={urllib.parse.quote(msg)}"


def _create_mayar_payment_link(order: dict, display_name: str, app_base_url: str) -> tuple[str, str]:
    api_key = _get_cfg("MAYAR_API_KEY")
    is_sandbox = _is_truthy(_get_cfg("MAYAR_IS_SANDBOX"))
    base = "https://api.mayar.club" if is_sandbox else "https://api.mayar.id"
    plan = PRO_PLANS[order["plan_code"]]
    email_val = order["user_id"] if "@" in order["user_id"] else f"{order['user_id']}@nutrisicerdas.local"
    payload = {
        "name": (display_name or order["user_id"])[:60],
        "email": email_val,
        "amount": int(order["amount_idr"]),
        "description": f"Nutrisi Cerdas {plan['name']} | {order['order_id']}",
        "redirectUrl": app_base_url or _get_cfg("APP_PUBLIC_URL", "https://nutrisi-cerdas.streamlit.app"),
        "extraData": {
            "order_id": order["order_id"],
            "user_id": order["user_id"],
            "plan_code": order["plan_code"],
        },
    }
    resp = requests.post(
        f"{base}/hl/v1/payment/create",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    inner = data.get("data") if isinstance(data, dict) else {}
    link = (inner or {}).get("link") or (inner or {}).get("paymentUrl") or data.get("link") or ""
    ext_ref = str((inner or {}).get("id") or (inner or {}).get("transactionId") or "")
    if not link:
        raise RuntimeError("Mayar API tidak mengembalikan tautan pembayaran.")
    return str(link), ext_ref


def _create_midtrans_snap_link(order: dict, display_name: str, app_base_url: str) -> tuple[str, str]:
    server_key = _get_cfg("MIDTRANS_SERVER_KEY")
    is_sandbox = _is_truthy(_get_cfg("MIDTRANS_IS_SANDBOX")) or server_key.startswith("SB-")
    endpoint = (
        "https://app.sandbox.midtrans.com/snap/v1/transactions"
        if is_sandbox else "https://app.midtrans.com/snap/v1/transactions"
    )
    auth_b64 = base64.b64encode(f"{server_key}:".encode("utf-8")).decode("ascii")
    plan = PRO_PLANS[order["plan_code"]]
    email_val = order["user_id"] if "@" in order["user_id"] else f"{order['user_id']}@nutrisicerdas.local"
    payload = {
        "transaction_details": {
            "order_id": order["order_id"],
            "gross_amount": int(order["amount_idr"]),
        },
        "item_details": [{
            "id": plan["code"],
            "price": int(order["amount_idr"]),
            "quantity": 1,
            "name": f"Nutrisi Cerdas - {plan['name']}"[:50],
        }],
        "customer_details": {
            "first_name": (display_name or order["user_id"])[:50],
            "email": email_val,
        },
        "enabled_payments": ["other_qris", "gopay", "shopeepay", "bca_va", "bri_va", "bni_va"],
        "callbacks": {
            "finish": app_base_url or _get_cfg("APP_PUBLIC_URL", "https://nutrisi-cerdas.streamlit.app"),
        },
    }
    resp = requests.post(
        endpoint,
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    redir = data.get("redirect_url") or ""
    tok = str(data.get("token") or "")
    if not redir:
        raise RuntimeError("Midtrans Snap tidak mengembalikan redirect_url.")
    return str(redir), tok


def create_qris_checkout(
    user_id: str,
    display_name: str,
    plan_code: str,
    app_base_url: str = "",
) -> tuple[bool, dict | str]:
    """Membuat pesanan Paket Pro + tautan QRIS sesuai gateway aktif (Mayar / Midtrans / Manual)."""
    clean_uid = str(user_id or "").strip().lower()
    if db_history.is_guest_user_id(clean_uid):
        return False, "Masuk atau buat akun gratis terlebih dahulu sebelum upgrade ke Paket Pro."
    code = str(plan_code or "PRO_30D").strip().upper()
    if code not in PRO_PLANS:
        return False, f"Paket tidak dikenal: {code}"

    plan = PRO_PLANS[code]
    gw = get_payment_gateway_status()
    now_dt = db_history.get_local_now(db_history.DEFAULT_TIMEZONE_OFFSET)
    draft_oid = f"NC-{code}-{now_dt.strftime('%Y%m%d')}-{os.urandom(3).hex().upper()}"
    draft_order = {
        "order_id": draft_oid,
        "user_id": clean_uid,
        "plan_code": code,
        "amount_idr": plan["amount_idr"],
        "days": plan["days"],
    }

    pay_url = ""
    ext_ref = ""
    provider = gw["mode"]

    try:
        if gw["mode"] == "mayar_api":
            pay_url, ext_ref = _create_mayar_payment_link(draft_order, display_name, app_base_url)
        elif gw["mode"] == "midtrans_snap":
            pay_url, ext_ref = _create_midtrans_snap_link(draft_order, display_name, app_base_url)
        elif gw["mode"] == "mayar_link":
            env_map = {
                "PRO_7D": "MAYAR_CHECKOUT_URL_7D",
                "PRO_30D": "MAYAR_CHECKOUT_URL_30D",
                "PRO_365D": "MAYAR_CHECKOUT_URL_365D",
            }
            pay_url = _get_cfg(env_map.get(code, "MAYAR_CHECKOUT_URL_30D")) or _get_cfg("MAYAR_CHECKOUT_URL_30D")
    except Exception as exc:
        return False, f"Gagal membuat tautan QRIS ({gw['label']}): {exc}"

    saved = db_history.create_payment_order(
        user_id=clean_uid,
        plan_code=code,
        amount_idr=plan["amount_idr"],
        days=plan["days"],
        provider=provider,
        payment_url=pay_url,
        external_ref=ext_ref,
        order_id=draft_oid,
    )
    saved["plan_name"] = plan["name"]
    saved["price_label"] = plan["price_label"]
    saved["wa_confirm_url"] = build_manual_wa_confirm_url(saved, display_name)
    return True, saved


def verify_midtrans_signature(
    order_id: str,
    status_code: str,
    gross_amount: str,
    signature_key: str,
    server_key: str = "",
) -> bool:
    """Memverifikasi tanda tangan SHA-512 resmi Midtrans (fail-closed jika MIDTRANS_SERVER_KEY kosong)."""
    key = (server_key or _get_cfg("MIDTRANS_SERVER_KEY")).strip()
    supplied = str(signature_key or "").strip().lower()
    if not key or not supplied:
        return False
    raw = f"{order_id}{status_code}{gross_amount}{key}".encode("utf-8")
    expected = hashlib.sha512(raw).hexdigest().lower()
    return hmac.compare_digest(expected, supplied)


def process_midtrans_notification(payload: dict, server_key: str = "") -> tuple[bool, int, str]:
    """Memproses notifikasi webhook Midtrans secara aman, fail-closed, dan idempoten."""
    if not isinstance(payload, dict):
        return False, 400, "Payload JSON tidak valid."
    key = (server_key or _get_cfg("MIDTRANS_SERVER_KEY")).strip()
    if not key:
        return False, 503, "MIDTRANS_SERVER_KEY belum dikonfigurasi di server."

    order_id = str(payload.get("order_id") or "").strip()
    status_code = str(payload.get("status_code") or "").strip()
    gross_amount = str(payload.get("gross_amount") or "").strip()
    sig = str(payload.get("signature_key") or "").strip()

    if not verify_midtrans_signature(order_id, status_code, gross_amount, sig, server_key=key):
        return False, 401, "Midtrans signature tidak valid."

    tx_status = str(payload.get("transaction_status") or "").strip().lower()
    fraud_status = str(payload.get("fraud_status") or "accept").strip().lower()
    tx_id = str(payload.get("transaction_id") or "").strip()

    if tx_status in {"settlement", "capture"} and fraud_status != "deny":
        try:
            paid_amt = int(round(float(gross_amount)))
        except (TypeError, ValueError):
            return False, 400, "gross_amount tidak valid."
        ok, res = db_history.mark_payment_order_paid(order_id, external_ref=tx_id, expected_amount=paid_amt)
        if not ok:
            return False, 400, str(res)
        if callable(send_system_alert):
            try:
                send_system_alert(
                    "Pembayaran Pro Midtrans Lunas",
                    f"Order {order_id} (Rp{paid_amt:,}) aktif untuk {res['user_id']} hingga {res.get('pro_until', '-')}.",
                    level="INFO",
                    dedupe_key=f"paid_{order_id}",
                )
            except Exception:
                pass
        return True, 200, "Paket Pro berhasil diaktifkan."

    return True, 200, f"Status transaksi {tx_status or 'unknown'} dicatat tanpa aktivasi."


def verify_mayar_webhook_token(supplied_token: str, expected_token: str = "") -> bool:
    """Memverifikasi token webhook Mayar.id secara fail-closed."""
    expected = (expected_token or _get_cfg("MAYAR_WEBHOOK_TOKEN")).strip()
    supplied = str(supplied_token or "").strip()
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def _extract_order_id_from_mayar(payload: dict) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    extra = data.get("extraData") if isinstance(data.get("extraData"), dict) else {}
    for candidate in (
        extra.get("order_id"),
        data.get("order_id"),
        payload.get("order_id"),
    ):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    for text_field in (data.get("description"), data.get("productName"), payload.get("description")):
        if text_field:
            m = _ORDER_ID_RE.search(str(text_field))
            if m:
                return m.group(0)
    return ""


def process_mayar_webhook(payload: dict, supplied_token: str, expected_token: str = "") -> tuple[bool, int, str]:
    """Memproses notifikasi webhook Mayar.id secara aman, fail-closed, dan idempoten."""
    exp = (expected_token or _get_cfg("MAYAR_WEBHOOK_TOKEN")).strip()
    if not exp:
        return False, 503, "MAYAR_WEBHOOK_TOKEN belum dikonfigurasi di server."
    if not verify_mayar_webhook_token(supplied_token, expected_token=exp):
        return False, 401, "Token webhook Mayar tidak valid."
    if not isinstance(payload, dict):
        return False, 400, "Payload JSON tidak valid."

    event = str(payload.get("event") or payload.get("status") or "").strip().lower()
    if event not in {"payment.received", "payment.success", "paid", "settlement"}:
        return True, 200, f"Event {event or 'unknown'} diabaikan."

    order_id = _extract_order_id_from_mayar(payload)
    if not order_id:
        return False, 400, "Order ID Nutrisi Cerdas tidak ditemukan pada payload Mayar."

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_amt = data.get("amount") if data.get("amount") is not None else payload.get("amount")
    exp_amt = None
    if raw_amt is not None:
        try:
            exp_amt = int(round(float(raw_amt)))
        except (TypeError, ValueError):
            return False, 400, "Nominal Mayar tidak valid."

    ext_ref = str(data.get("transactionId") or data.get("id") or "")
    ok, res = db_history.mark_payment_order_paid(order_id, external_ref=ext_ref, expected_amount=exp_amt)
    if not ok:
        return False, 400, str(res)

    if callable(send_system_alert):
        try:
            send_system_alert(
                "Pembayaran Pro Mayar Lunas",
                f"Order {order_id} aktif untuk {res['user_id']} hingga {res.get('pro_until', '-')}.",
                level="INFO",
                dedupe_key=f"paid_{order_id}",
            )
        except Exception:
            pass
    return True, 200, "Paket Pro berhasil diaktifkan."

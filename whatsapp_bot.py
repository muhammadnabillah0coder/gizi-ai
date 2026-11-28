"""
WhatsApp Webhook Bot untuk Nutrisi Cerdas.
Mendukung:
1. Penerimaan pesan teks / foto makanan dari pengguna via WhatsApp (Fonnte / Wablas / Meta Cloud API).
2. Analisis nutrisi berbasis database lab TKPI Kemenkes & Auto-Learning AI.
3. Pencatatan otomatis ke tabel meal_logs pengguna (Sinkron langsung ke dashboard web).
4. Balasan WhatsApp instan dengan rincian kalori, makronutrien, dan magic link ke dashboard web.
"""

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse
import hmac
import ipaddress
import requests
import os
import io
import socket
import urllib.parse
from PIL import Image
from datetime import datetime

from gemini_extractor import analyze_food_text, analyze_food_image
from nutrition_engine import calculate_dish_nutrition
from food_guardrails import FoodGuardrailRejected, open_safe_image, validate_extracted_dish_totals
from db_history import (
    init_user_history_tables, get_or_create_user, log_meal, get_user_history_stats,
    get_user_scan_status, record_scan_usage, get_local_now,
    create_session_token, is_admin_user
)
from payment_gateway import process_midtrans_notification, process_mayar_webhook

app = FastAPI(title="Nutrisi Cerdas WhatsApp Bot API")


@app.on_event("startup")
def _startup_init_db():
    init_user_history_tables()

DASHBOARD_BASE_URL = "https://nutrisi-cerdas.streamlit.app"
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _dashboard_url(user_id: str) -> str:
    clean_uid = (user_id or "").strip().lower()
    if not clean_uid or is_admin_user(clean_uid):
        return DASHBOARD_BASE_URL
    token = create_session_token(clean_uid)
    if not token:
        return DASHBOARD_BASE_URL
    return f"{DASHBOARD_BASE_URL}/?u={urllib.parse.quote(clean_uid)}&s={token}"


def _verify_webhook_secret(request: Request, data: dict) -> tuple[bool, int, str]:
    expected = (os.environ.get("WHATSAPP_WEBHOOK_SECRET") or "").strip()
    if not expected:
        return False, 503, "WHATSAPP_WEBHOOK_SECRET belum dikonfigurasi di server."

    auth_hdr = (request.headers.get("authorization") or "").strip()
    bearer_tok = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
    supplied = (
        request.headers.get("x-webhook-secret")
        or bearer_tok
        or str(data.get("secret") or "")
    ).strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        return False, 401, "Unauthorized webhook request."
    return True, 200, ""


def _is_safe_public_https_url(raw_url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse((raw_url or "").strip())
    except Exception:
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "ip6-localhost"} or host.endswith(".local"):
        return False
    try:
        port = parsed.port or 443
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return False
    if not addr_infos:
        return False
    for info in addr_infos:
        ip_str = info[4][0].split("%")[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        if (
            not getattr(ip_obj, "is_global", True)
            or ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_multicast
            or ip_obj.is_reserved
            or ip_obj.is_unspecified
        ):
            return False
    return True


def _download_image_bytes(image_url: str) -> bytes:
    if not _is_safe_public_https_url(image_url):
        raise ValueError("URL gambar harus berupa HTTPS publik yang valid.")
    with requests.get(image_url, timeout=15, allow_redirects=False, stream=True) as resp:
        resp.raise_for_status()
        chunks = []
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > _MAX_IMAGE_BYTES:
                raise ValueError("Ukuran gambar melebihi batas maksimum 10 MB.")
            chunks.append(chunk)
    return b"".join(chunks)

def format_wa_reply(sender_phone: str, dish_name: str, totals: dict, advice: str = "") -> str:
    """Format balasan WhatsApp yang rapi, ramah, dan memotivasi."""
    stats = get_user_history_stats(sender_phone)
    today_kcal = stats["today_totals"]["energy_kcal"]
    
    reply = (
        f"🥗 *Nutrisi Cerdas - Catatan Makanan*\n\n"
        f"✅ *Menu:* {dish_name}\n"
        f"🔥 *Energi:* {totals.get('energy_kcal', 0)} kkal\n"
        f"🥩 *Protein:* {totals.get('protein_g', 0)}g\n"
        f"🥑 *Lemak:* {totals.get('fat_g', 0)}g\n"
        f"🍚 *Karbohidrat:* {totals.get('carb_g', 0)}g\n"
        f"🌿 *Serat:* {totals.get('fiber_g', 0)}g\n"
    )
    
    if advice:
        reply += f"\n💡 *Catatan Nutrisi Cerdas:*\n_{advice}_\n"
        
    reply += (
        f"\n📊 *Total Kalori Hari Ini:* {today_kcal:,.1f} kkal\n\n"
        f"Lihat grafik cincin aktivitas & tren mingguanmu di:\n"
        f"👉 {_dashboard_url(sender_phone)}\n\n"
        f"_Ketik nama makanan atau kirim foto piringmu lagi kapan saja!_"
    )
    return reply

@app.get("/")
def home():
    return {"status": "active", "service": "Nutrisi Cerdas WhatsApp Bot Webhook"}

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """
    Webhook universal untuk menerima payload pesan WhatsApp (Kompatibel dengan Fonnte, Wablas, atau custom webhook).
    """
    try:
        data = await request.json()
    except:
        form = await request.form()
        data = dict(form)

    ok_sec, sec_code, sec_err = _verify_webhook_secret(request, data)
    if not ok_sec:
        return JSONResponse({"status": "error", "reason": sec_err}, status_code=sec_code)
        
    sender = data.get("sender") or data.get("from") or data.get("phone", "")
    message_text = data.get("message") or data.get("text", "")
    image_url = data.get("url") or data.get("image") or data.get("media_url", "")
    
    if not sender:
        return JSONResponse({"status": "ignored", "reason": "No sender phone found"})
        
    sender_clean = sender.replace("+", "").replace("-", "").replace(" ", "").split("@")[0]
    
    # Pastikan profil user terdaftar di database
    user = get_or_create_user(sender_clean, display_name=f"WA User ({sender_clean[-4:]})", auth_provider="whatsapp")
    scan_status = get_user_scan_status(sender_clean)
    
    api_key = os.environ.get("GEMINI_API_KEY", "")
    
    # 1. Kasus Kirim Foto Makanan
    if image_url:
        if not scan_status["can_scan"]:
            max_sc = scan_status.get("max_scans", 5)
            return {
                "reply": (
                    f"⚠️ *Batas Scan Foto Beta Tercapai ({max_sc}/{max_sc} Hari Ini)*\n\n"
                    f"Kamu masih bisa catat makanan lewat ketik teks atau 1-Klik Menu Harian sepuasnya secara gratis!\n\n"
                    f"Lihat riwayat lengkapmu di:\n"
                    f"👉 {_dashboard_url(sender_clean)}"
                )
            }
            
        try:
            # Download gambar dari link WhatsApp gateway dengan validasi SSRF, ukuran byte, & batas piksel
            img_bytes = _download_image_bytes(image_url)
            pil_img = open_safe_image(io.BytesIO(img_bytes))
            
            ai_data = analyze_food_image(pil_img, caption=message_text, api_key=api_key)
            record_scan_usage(sender_clean)
            
            dish_name = ai_data.get("dish_name", "Menu Pilihan")
            components = ai_data.get("components", [])
            nutrition_calc = calculate_dish_nutrition(components, auto_learn=False)
            totals = nutrition_calc["totals"]
            validate_extracted_dish_totals(dish_name, totals)
            
            # Tentukan meal_type otomatis berdasarkan jam lokal WITA
            hour = get_local_now().hour
            if hour < 11:
                meal_type = "Sarapan"
            elif hour < 16:
                meal_type = "Makan Siang"
            elif hour < 20:
                meal_type = "Makan Malam"
            else:
                meal_type = "Camilan"
                
            log_meal(sender_clean, dish_name, totals, multiplier=1.0, caption="Catatan via WhatsApp", meal_type=meal_type)
            reply_msg = format_wa_reply(sender_clean, dish_name, totals, advice=ai_data.get("health_tip", ""))
            return {"reply": reply_msg}
        except FoodGuardrailRejected as g_err:
            if g_err.consumes_scan_quota:
                record_scan_usage(sender_clean)
            return {"reply": f"🛡️ *Tidak Dapat Diproses*\n\n{g_err.message}"}
        except Exception as e:
            print(f"[WA FOTO ERROR]: {type(e).__name__}: {e}")
            return {"reply": "Maaf, gagal memproses foto makanan Anda saat ini. Pastikan foto cukup terang dan coba lagi."}

    # 2. Kasus Kirim Pesan Teks
    elif message_text:
        # Jika user menyapa
        if message_text.lower().strip() in ["halo", "hi", "hai", "menu", "help", "bantuan", "start"]:
            return {
                "reply": (
                    f"Halo! 🥗 Saya asisten AI *Nutrisi Cerdas*.\n\n"
                    f"Kirimkan *foto makananmu* atau *ketik apa yang kamu makan* (contoh: _1 mangkok bakso campur tahu_), dan saya akan langsung menghitung kalori serta nutrisinya berdasarkan data resmi lab pangan Kemenkes RI!\n\n"
                    f"Buka dashboard pribadimu:\n👉 {_dashboard_url(sender_clean)}"
                )
            }
            
        try:
            ai_data = analyze_food_text(message_text, api_key=api_key)
            dish_name = ai_data.get("dish_name", message_text.capitalize())
            components = ai_data.get("components", [])
            nutrition_calc = calculate_dish_nutrition(components, auto_learn=False)
            totals = nutrition_calc["totals"]
            validate_extracted_dish_totals(dish_name, totals)
            
            hour = get_local_now().hour
            meal_type = "Sarapan" if hour < 11 else ("Makan Siang" if hour < 16 else ("Makan Malam" if hour < 20 else "Camilan"))
            log_meal(sender_clean, dish_name, totals, multiplier=1.0, caption="Catatan teks WA", meal_type=meal_type)
            
            reply_msg = format_wa_reply(sender_clean, dish_name, totals, advice=ai_data.get("health_tip", ""))
            return {"reply": reply_msg}
        except FoodGuardrailRejected as g_err:
            return {"reply": f"🛡️ *Tidak Dapat Diproses*\n\n{g_err.message}"}
        except Exception as e:
            print(f"[WA TEKS ERROR]: {type(e).__name__}: {e}")
            return {"reply": "Maaf, terjadi kendala saat menganalisis pesan makanan tersebut. Silakan coba beberapa saat lagi."}
            
    return {"reply": "Kirimkan teks nama makanan atau foto piringmu untuk saya hitung profil nutrisinya secara akurat!"}


@app.post("/webhook/midtrans")
async def midtrans_qris_webhook(request: Request):
    """Webhook resmi Midtrans Snap/QRIS dengan verifikasi tanda tangan SHA-512 & aktivasi Pro idempoten."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Payload JSON tidak valid."})
    ok, status_code, message = process_midtrans_notification(payload)
    return JSONResponse(status_code=status_code, content={"ok": ok, "message": message})


@app.post("/webhook/mayar")
async def mayar_qris_webhook(request: Request):
    """Webhook resmi Mayar.id QRIS dengan validasi token header fail-closed & aktivasi Pro idempoten."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Payload JSON tidak valid."})
    auth_hdr = (request.headers.get("authorization") or "").strip()
    bearer = auth_hdr[7:].strip() if auth_hdr.lower().startswith("bearer ") else ""
    supplied = (
        request.headers.get("x-callback-token")
        or request.headers.get("x-mayar-token")
        or bearer
        or ""
    ).strip()
    ok, status_code, message = process_mayar_webhook(payload, supplied_token=supplied)
    return JSONResponse(status_code=status_code, content={"ok": ok, "message": message})


if __name__ == "__main__":
    import uvicorn
    dev_reload = os.environ.get("DEV_RELOAD", "").strip().lower() == "true"
    uvicorn.run("whatsapp_bot:app", host="0.0.0.0", port=8000, reload=dev_reload)

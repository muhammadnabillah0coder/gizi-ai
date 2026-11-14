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
import requests
import os
import io
from PIL import Image
from datetime import datetime

from gemini_extractor import analyze_food_text, analyze_food_image
from nutrition_engine import calculate_dish_nutrition
from db_history import (
    get_or_create_user, log_meal, get_user_history_stats,
    get_user_scan_status, record_scan_usage, get_local_now, create_session_token
)

app = FastAPI(title="Nutrisi Cerdas WhatsApp Bot API")

DASHBOARD_BASE_URL = "https://nutrisi-cerdas.streamlit.app"

def _dashboard_url(user_id: str) -> str:
    token = create_session_token(user_id)
    return f"{DASHBOARD_BASE_URL}/?u={user_id}&s={token}" if token else DASHBOARD_BASE_URL

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
            # Download gambar dari link WhatsApp gateway
            img_res = requests.get(image_url, timeout=15)
            pil_img = Image.open(io.BytesIO(img_res.content))
            
            ai_data = analyze_food_image(pil_img, caption=message_text, api_key=api_key)
            record_scan_usage(sender_clean)
            
            dish_name = ai_data.get("dish_name", "Menu Pilihan")
            components = ai_data.get("components", [])
            nutrition_calc = calculate_dish_nutrition(components)
            totals = nutrition_calc["totals"]
            
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
        except Exception as e:
            return {"reply": f"Maaf, gagal memproses foto: {str(e)}. Coba kirim ulang dengan foto lebih jelas ya!"}

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
            nutrition_calc = calculate_dish_nutrition(components)
            totals = nutrition_calc["totals"]
            
            hour = get_local_now().hour
            meal_type = "Sarapan" if hour < 11 else ("Makan Siang" if hour < 16 else ("Makan Malam" if hour < 20 else "Camilan"))
            log_meal(sender_clean, dish_name, totals, multiplier=1.0, caption="Catatan teks WA", meal_type=meal_type)
            
            reply_msg = format_wa_reply(sender_clean, dish_name, totals, advice=ai_data.get("health_tip", ""))
            return {"reply": reply_msg}
        except Exception as e:
            return {"reply": f"Maaf, tidak dapat menganalisis teks tersebut: {str(e)}"}
            
    return {"reply": "Kirimkan teks nama makanan atau foto piringmu untuk saya hitung profil nutrisinya secara akurat!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("whatsapp_bot:app", host="0.0.0.0", port=8000, reload=True)

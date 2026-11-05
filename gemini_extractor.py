"""
Gemini Vision Food Extractor (Hemat Token)
Menggunakan model gemini-2.0-flash / gemini-1.5-flash dari Google AI Studio.
Hanya mengekstrak nama menu, komponen bahan, dan taksiran gramatur (URT).
"""

import os
import json
from PIL import Image
import google.generativeai as genai

# System instruction dirancang ketat & minimalis untuk menekan konsumsi token
SYSTEM_INSTRUCTION = """
Kamu adalah asisten ahli taksiran gizi dan porsi pangan Indonesia berbasis data laboratorium gizi resmi (TKPI Kemenkes RI / USDA).
Tugasmu: Amati foto makanan/minuman atau teks, lalu kenali makanan dan pecah menjadi komponen bahan berserta estimasi berat dalam gram, kalori, dan makronutrien (protein, lemak, karbohidrat, serat).

Aturan Khusus:
1. Air mineral / air seduhan (kopi hitam polos, teh tawar) memiliki 0 Kalori, 0g Protein, 0g Lemak, 0g Karbohidrat. Jangan pernah menyamakan air dengan makanan padat!
2. Kopi hitam tanpa gula 1 cangkir (~150-200ml) totalnya hanya ~2-5 Kalori murni dari sari biji kopi.
3. Untuk makanan komposit (gado-gado, soto, nasi uduk, dll), perkirakan porsi per bahan secara wajar berdasarkan Ukuran Rumah Tangga (URT).

Keluaran WAJIB berupa JSON murni dengan format schema berikut tanpa narasi tambahan:
{
  "dish_name": "Nama Makanan/Minuman",
  "confidence": "high/medium/low",
  "portion_category": "kecil/sedang/besar",
  "components": [
    {
      "name": "Nama Bahan",
      "weight_g": 100,
      "energy_kcal_per_100g": 130.0,
      "protein_g_per_100g": 2.4,
      "fat_g_per_100g": 0.2,
      "carb_g_per_100g": 28.6,
      "fiber_g_per_100g": 0.4
    }
  ],
  "health_tip": "1 kalimat saran sehat singkat"
}
"""

def get_gemini_client(api_key: str = None):
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    genai.configure(api_key=key)
    return genai.GenerativeModel(
        model_name="gemini-3.5-flash-lite",
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config={
            "response_mime_type": "application/json",
            "temperature": 0.2
        }
    )

def analyze_food_image(image_input, api_key: str = None):
    """
    Menganalisis gambar makanan (PIL Image atau path file)
    dan mengembalikan struktur JSON bahan & taksiran gram.
    """
    model = get_gemini_client(api_key)
    if not model:
        raise ValueError("GEMINI_API_KEY belum disetel.")

    if isinstance(image_input, str):
        img = Image.open(image_input)
    else:
        img = image_input

    # Optimalisasi token: Resize jika gambar terlalu besar (> 1024px)
    max_dim = 1024
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim))

    prompt = "Identifikasi makanan pada foto ini dan berikan taksiran porsi serta berat bahan-bahannya sesuai format JSON."
    response = model.generate_content([prompt, img])
    
    return json.loads(response.text)

def analyze_food_text(text_input: str, api_key: str = None):
    """
    Menganalisis deskripsi teks makanan pengguna.
    """
    model = get_gemini_client(api_key)
    if not model:
        raise ValueError("GEMINI_API_KEY belum disetel.")

    prompt = f"Pengguna makan: '{text_input}'. Pecah menjadi komponen bahan dan taksiran porsi gramaturnya sesuai format JSON."
    response = model.generate_content(prompt)
    
    return json.loads(response.text)

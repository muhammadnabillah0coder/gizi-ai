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
Kamu adalah asisten ahli taksiran porsi pangan Indonesia berbasis Ukuran Rumah Tangga (URT).
Tugasmu: Amati foto makanan atau deskripsi teks, lalu kenali makanan dan pecah ke dalam komponen bahan berserta estimasi berat dalam gram.

Pedoman Ukuran Rumah Tangga (URT) Porsi Indonesia:
- 1 centong nasi putih = ~100g
- 1 piring lontong = ~100-120g
- 1 potong ayam sedang = ~70-80g
- 1 butir telur = ~55g
- 1 potong tahu/tempe sedang = ~35-40g
- 1 porsi sayuran rebus campur = ~100-120g
- Bumbu kacang (gado-gado/sate) = ~40-60g
- 1 mangkok kuah soto/sop = ~150-200g
- Kerupuk = ~15g

Keluaran WAJIB berupa JSON murni dengan format schema berikut tanpa narasi tambahan:
{
  "dish_name": "Nama Makanan",
  "confidence": "high/medium/low",
  "portion_category": "kecil/sedang/besar",
  "components": [
    {"name": "Nama Bahan", "weight_g": 100}
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

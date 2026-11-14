"""
Gemini Vision Food Extractor (Hemat Token + Cache Menu Populer)
Mengekstrak nama menu, komponen bahan, dan taksiran gramatur (URT).
"""

import os
import json
import copy
import warnings
from collections import OrderedDict
from PIL import Image

# Dukungan kompatibel google.genai (baru) atau google.generativeai (existing)
try:
    from google import genai as google_genai_sdk
    from google.genai import types as google_genai_types
    _HAS_NEW_GENAI = True
except ImportError:
    _HAS_NEW_GENAI = False

with warnings.catch_warnings():
    warnings.simplefilter("ignore", FutureWarning)
    try:
        import google.generativeai as genai_legacy
    except ImportError:
        genai_legacy = None

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"

# Cache hasil teks dalam memori untuk menekan biaya token saat menu serupa dicatat berulang
_TEXT_ANALYSIS_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_MAX_CACHE_ITEMS = 200

class GeminiExtractionError(RuntimeError):
    """Error ramah pengguna saat ekstraksi AI gagal / limit tercapai."""
    pass

# System instruction dirancang ketat & minimalis untuk menekan konsumsi token
SYSTEM_INSTRUCTION = """
Kamu adalah Nutrisi Cerdas AI Engine: sistem pakar taksiran porsi dan analisis pangan Indonesia berbasis data laboratorium resmi (TKPI Kemenkes RI & USDA FoodData).
Tugasmu: Amati foto makanan/minuman atau teks, kenali hidangan, dan uraikan menjadi komponen bahan berserta estimasi berat dalam gram (URT Indonesia), kalori, dan makronutrien (protein, lemak, karbohidrat, serat).

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

def _normalize_text_key(text_input: str) -> str:
    return " ".join((text_input or "").strip().lower().split())

def _friendly_ai_error(exc: Exception) -> GeminiExtractionError:
    msg = str(exc)
    low = msg.lower()
    if "429" in low or "quota" in low or "resource_exhausted" in low or "rate" in low:
        return GeminiExtractionError(
            "Server AI sedang ramai atau kuota harian tercapai sesaat. "
            "Silakan coba lagi dalam 1 menit, atau gunakan '1-Klik Menu Harian', 'Barcode', atau 'Pencarian Database'."
        )
    if "api_key" in low or "api key" in low or "permission" in low or "403" in low or "401" in low:
        return GeminiExtractionError(
            "Kunci API AI tidak valid atau belum aktif. Hubungi Admin untuk memeriksa konfigurasi Secrets."
        )
    if "timeout" in low or "timed out" in low or "connection" in low:
        return GeminiExtractionError(
            "Koneksi ke layanan AI terputus atau terlalu lambat. Periksa jaringan internet Anda lalu coba ulang."
        )
    return GeminiExtractionError(f"AI belum dapat mengenali menu saat ini ({msg[:120]}). Coba foto lebih terang atau ketik nama menunya.")

def _parse_json_payload(raw_text: str) -> dict:
    clean = (raw_text or "").strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.startswith("json"):
            clean = clean[4:].strip()
    return json.loads(clean)

def get_gemini_client(api_key: str = None):
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    if _HAS_NEW_GENAI:
        return ("new", google_genai_sdk.Client(api_key=key))
    if genai_legacy is not None:
        genai_legacy.configure(api_key=key)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        return ("legacy", genai_legacy.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2
            }
        ))
    return None

def analyze_food_image(image_input, caption: str = "", api_key: str = None):
    """
    Menganalisis gambar makanan (PIL Image atau path file) beserta caption/keterangan tambahan opsional
    dan mengembalikan struktur JSON bahan & taksiran gram.
    """
    client_pair = get_gemini_client(api_key)
    if not client_pair:
        raise ValueError("GEMINI_API_KEY belum disetel.")

    if isinstance(image_input, str):
        img = Image.open(image_input)
    else:
        img = image_input

    # Optimalisasi token: Resize jika gambar terlalu besar (> 1024px)
    max_dim = 1024
    if max(img.size) > max_dim:
        img = img.copy()
        img.thumbnail((max_dim, max_dim))

    prompt = "Identifikasi makanan pada foto ini dan berikan taksiran porsi serta berat bahan-bahannya sesuai format JSON."
    if caption and caption.strip():
        prompt += f"\nCatatan/keterangan tambahan dari pengguna: '{caption.strip()}' (Gunakan catatan ini untuk memperjelas bahan tersembunyi, bumbu, atau taksiran porsi riil)."

    sdk_kind, client_obj = client_pair
    try:
        if sdk_kind == "new":
            resp = client_obj.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                contents=[prompt, img],
                config=google_genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            return _parse_json_payload(resp.text)
        else:
            response = client_obj.generate_content([prompt, img])
            return _parse_json_payload(response.text)
    except Exception as exc:
        raise _friendly_ai_error(exc) from exc

def analyze_food_text(text_input: str, api_key: str = None, use_cache: bool = True):
    """
    Menganalisis deskripsi teks makanan pengguna (memakai cache memori untuk hemat kuota API).
    """
    norm_key = _normalize_text_key(text_input)
    if use_cache and norm_key in _TEXT_ANALYSIS_CACHE:
        _TEXT_ANALYSIS_CACHE.move_to_end(norm_key)
        return copy.deepcopy(_TEXT_ANALYSIS_CACHE[norm_key])

    client_pair = get_gemini_client(api_key)
    if not client_pair:
        raise ValueError("GEMINI_API_KEY belum disetel.")

    prompt = f"Pengguna makan: '{text_input}'. Pecah menjadi komponen bahan dan taksiran porsi gramaturnya sesuai format JSON."
    sdk_kind, client_obj = client_pair
    try:
        if sdk_kind == "new":
            resp = client_obj.models.generate_content(
                model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                contents=prompt,
                config=google_genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            parsed = _parse_json_payload(resp.text)
        else:
            response = client_obj.generate_content(prompt)
            parsed = _parse_json_payload(response.text)
    except Exception as exc:
        raise _friendly_ai_error(exc) from exc

    if use_cache and norm_key:
        _TEXT_ANALYSIS_CACHE[norm_key] = copy.deepcopy(parsed)
        _TEXT_ANALYSIS_CACHE.move_to_end(norm_key)
        while len(_TEXT_ANALYSIS_CACHE) > _MAX_CACHE_ITEMS:
            _TEXT_ANALYSIS_CACHE.popitem(last=False)

    return parsed

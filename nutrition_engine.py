"""
Nutrition Calculator & Matcher Engine
Mencari padanan item hasil deteksi AI ke Database TKPI Kemenkes dan menghitung nilai gizi.
0 Token AI digunakan dalam perhitungan matematika ini.
"""

import sqlite3
import os
import re
import difflib
import threading

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")
_CATALOG_LOCK = threading.Lock()
_FOOD_CATALOG_CACHE = None
_FOOD_CATALOG_META = ("", 0.0)

# Kamus bahan pokok Indonesia -> nama tepat di database TKPI Kemenkes
BASE_INGREDIENT_SYNONYMS = {
    "gula": "Gula putih (Sugar cane)",
    "gula pasir": "Gula putih (Sugar cane)",
    "gula putih": "Gula putih (Sugar cane)",
    "gula tebu": "Gula putih (Sugar cane)",
    "gula merah": "Gula aren (Sugar, palm)",
    "gula aren": "Gula aren (Sugar, palm)",
    "gula jawa": "Gula kelapa",
    "pisang": "Pisang ambon, segar (Banana, fresh)",
    "pisang segar": "Pisang ambon, segar (Banana, fresh)",
    "pisang ambon": "Pisang ambon, segar (Banana, fresh)",
    "pisang kepok": "Pisang kepok, segar (Banana, kepok, fresh)",
    "pepaya": "Pepaya, segar (Papaya, fresh)",
    "pepaya potong": "Pepaya, segar (Papaya, fresh)",
    "pepaya segar": "Pepaya, segar (Papaya, fresh)",
    "buah pepaya": "Pepaya, segar (Papaya, fresh)",
    "telur": "Telur ayam ras, segar (Domestic chicken, egg, fresh)",
    "telur ayam": "Telur ayam ras, segar (Domestic chicken, egg, fresh)",
    "telur segar": "Telur ayam ras, segar (Domestic chicken, egg, fresh)",
    "telur mentah": "Telur ayam ras, segar (Domestic chicken, egg, fresh)",
    "telur rebus": "Telur ayam rebus",
    "ayam": "Ayam, daging, segar (Chicken, meat, fresh)",
    "daging ayam": "Ayam, daging, segar (Chicken, meat, fresh)",
    "ayam segar": "Ayam, daging, segar (Chicken, meat, fresh)",
    "nasi": "Nasi putih",
    "nasi putih": "Nasi putih",
    "minyak": "Minyak kelapa sawit (Palm oil)",
    "minyak goreng": "Minyak kelapa sawit (Palm oil)",
    "minyak sawit": "Minyak kelapa sawit (Palm oil)",
    "santan": "Santan (dengan air) (Coconut milk mixed with water)",
    "santan kelapa": "Santan (dengan air) (Coconut milk mixed with water)",
    "santan encer": "Santan (dengan air) (Coconut milk mixed with water)",
    "santan kental": "Santan murni (Coconut milk, pured)",
    "santan murni": "Santan murni (Coconut milk, pured)",
    "tepung": "Tepung terigu",
    "tepung terigu": "Tepung terigu",
    "terigu": "Tepung terigu",
    "tepung beras": "Tepung beras, mentah",
    "tahu": "Tahu, mentah",
    "tahu putih": "Tahu, mentah",
    "tempe": "Tempe pasar",
    "tempe mentah": "Tempe pasar",
    "susu": "Susu sapi, segar",
    "susu sapi": "Susu sapi, segar",
    "susu segar": "Susu sapi, segar",
    "roti": "Roti putih",
    "roti tawar": "Roti putih",
    "kecap": "Kecap (Soyabean sauce)",
    "kecap manis": "Kecap (Soyabean sauce)",
    "bawang merah": "Bawang merah, segar (Shallot)",
    "bawang putih": "Bawang putih, segar (Garlic)",
    "bingka": "Bingka",
    "kue bingka": "Bingka",
    "bingka pisang": "Bingka",
}

COOKING_MODIFIERS = {
    "goreng", "tepung", "balado", "gulai", "rendang", "keripik",
    "pepes", "bakar", "panggang", "tumis", "rebus", "bacem", "kuah", "masakan"
}


def _strip_tkpi_parens(name: str) -> str:
    return re.sub(r"\s*\([^)]*\)", "", name or "").strip()


def compute_macro_targets(target_kcal: float, focus_goal: str = "Diet Sehat") -> dict:
    """Menghitung target gram makronutrien, serat, dan natrium harian sesuai fokus klinis."""
    kcal = max(800.0, float(target_kcal or 2000.0))
    focus_low = (focus_goal or "Diet Sehat").lower()
    if "hamil" in focus_low:
        p_pct, f_pct, c_pct, fib_g, sod_mg = 0.22, 0.28, 0.50, 28.0, 2000.0
    elif "diabetes" in focus_low or "gula" in focus_low:
        p_pct, f_pct, c_pct, fib_g, sod_mg = 0.22, 0.33, 0.45, 30.0, 2000.0
    elif "hipertensi" in focus_low or "natrium" in focus_low:
        p_pct, f_pct, c_pct, fib_g, sod_mg = 0.20, 0.28, 0.52, 28.0, 1500.0
    else:
        p_pct, f_pct, c_pct, fib_g, sod_mg = 0.22, 0.28, 0.50, 25.0, 2000.0

    return {
        "protein_g": round((kcal * p_pct) / 4.0, 1),
        "fat_g": round((kcal * f_pct) / 9.0, 1),
        "carb_g": round((kcal * c_pct) / 4.0, 1),
        "fiber_g": fib_g,
        "sodium_mg": sod_mg,
    }


def invalidate_food_catalog_cache():
    """Menghapus cache RAM katalog TKPI saat ada pembaruan katalog."""
    global _FOOD_CATALOG_CACHE, _FOOD_CATALOG_META
    with _CATALOG_LOCK:
        _FOOD_CATALOG_CACHE = None
        _FOOD_CATALOG_META = ("", 0.0)


def _get_cached_food_catalog():
    """Memuat katalog TKPI ke memori sekali (otomatis refresh bila file DB berubah)."""
    global _FOOD_CATALOG_CACHE, _FOOD_CATALOG_META
    try:
        cur_mtime = os.path.getmtime(DB_PATH)
    except OSError:
        cur_mtime = 0.0

    with _CATALOG_LOCK:
        if _FOOD_CATALOG_CACHE is not None and _FOOD_CATALOG_META == (DB_PATH, cur_mtime):
            return _FOOD_CATALOG_CACHE

        conn = get_db_connection()
        cur = conn.cursor()
        raw_rows = cur.execute("SELECT * FROM food_composition").fetchall()
        conn.close()

        indexed = []
        for raw in raw_rows:
            d = dict(raw)
            fname_low = (d.get("food_name") or "").lower()
            core_name = _strip_tkpi_parens(fname_low)
            core_tokens = tuple(t for t in re.split(r"[\s,]+", core_name) if t)
            indexed.append({
                "row": d,
                "fname_low": fname_low,
                "core_name": core_name,
                "core_tokens": core_tokens,
            })

        _FOOD_CATALOG_CACHE = indexed
        _FOOD_CATALOG_META = (DB_PATH, cur_mtime)
        return _FOOD_CATALOG_CACHE


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_best_match(query_name: str):
    """
    Mencari kecocokan terbaik di database TKPI dengan scoring prioritas:
    1. Special drinks (air, kopi, teh)
    2. Barcode lookup (lokal + Open Food Facts)
    3. Exact match & Kamus sinonim bahan dasar Indonesia
    4. Core-name match tanpa teks kurung Inggris + penalti olahan jika tak diminta
    5. Strict fuzzy match (cutoff 0.85) agar tidak salah cocok antar bahan berbeda
    """
    catalog = _get_cached_food_catalog()

    query_lower = " ".join((query_name or "").lower().strip().split())
    if not query_lower:
        return None

    # 1. Pengecualian khusus: Air mineral / seduhan
    if query_lower in ["air", "air putih", "air mineral", "air panas", "air dingin"]:
        return {
            "food_name": "Air Mineral",
            "category": "Minuman",
            "bdd_rate": 100.0,
            "energy_kcal": 0.0,
            "protein_g": 0.0,
            "fat_g": 0.0,
            "carb_g": 0.0,
            "fiber_g": 0.0,
            "sodium_mg": 0.0
        }
    if query_lower in ["kopi", "kopi hitam", "kopi hitam polos", "kopi polos", "kopi tubruk tanpa gula", "kopi tanpa gula"]:
        return {
            "food_name": "Kopi hitam tanpa gula",
            "category": "Minuman",
            "bdd_rate": 100.0,
            "energy_kcal": 2.0,
            "protein_g": 0.1,
            "fat_g": 0.0,
            "carb_g": 0.3,
            "fiber_g": 0.0,
            "sodium_mg": 3.0
        }
    if query_lower in ["teh", "teh tawar", "es teh tawar", "teh hangat tawar"]:
        return {
            "food_name": "Es teh tawar",
            "category": "Minuman",
            "bdd_rate": 100.0,
            "energy_kcal": 1.0,
            "protein_g": 0.0,
            "fat_g": 0.0,
            "carb_g": 0.2,
            "fiber_g": 0.0,
            "sodium_mg": 3.0
        }

    # 1.5. Cek pencarian via Barcode jika input berupa angka (8-14 digit)
    clean_digits = "".join(filter(str.isdigit, query_name))
    if len(clean_digits) >= 8:
        for entry in catalog:
            row = entry["row"]
            if row.get("barcode") and clean_digits in str(row["barcode"]):
                return dict(row)
        # Jika belum ada di database lokal, coba tarik real-time dari Open Food Facts API
        off_product = fetch_open_food_facts(clean_digits)
        if off_product:
            return off_product

    # 2. Kamus sinonim bahan pokok Indonesia (anti salah cocok olahan/sayur)
    syn_target = BASE_INGREDIENT_SYNONYMS.get(query_lower)
    if syn_target:
        syn_low = syn_target.lower()
        for entry in catalog:
            if entry["fname_low"] == syn_low:
                return dict(entry["row"])

    # 3. Cek exact match langsung (penuh atau tanpa terjemahan dalam kurung)
    for entry in catalog:
        if query_lower == entry["fname_low"] or query_lower == entry["core_name"]:
            return dict(entry["row"])

    # 4. Word-boundary & substring scoring pada nama inti TKPI (bebas penalti teks Inggris)
    matching_substrings = []
    query_words = [w for w in re.split(r"[\s,]+", query_lower) if len(w) >= 3]
    query_wants_modifier = any(mod in query_words for mod in COOKING_MODIFIERS)

    for entry in catalog:
        core_name = entry["core_name"]
        core_tokens = entry["core_tokens"]

        base_score = 0.0
        if len(query_lower) >= 3 and re.search(rf"\b{re.escape(query_lower)}\b", core_name):
            starts_bonus = 2.0 if core_name.startswith(query_lower) else 1.2
            base_score = (len(query_lower) / max(len(core_name), 1)) * starts_bonus
        elif query_words and all(any(tok == w or tok.startswith(w) for tok in core_tokens) for w in query_words):
            starts_bonus = 1.6 if core_tokens and core_tokens[0] == query_words[0] else 1.0
            base_score = (sum(len(w) for w in query_words) / max(len(core_name), 1)) * starts_bonus

        if base_score > 0:
            # Jika pengguna mencari bahan mentah/sederhana, beri penalti pada masakan/olahan goreng
            if not query_wants_modifier and any(tok in COOKING_MODIFIERS for tok in core_tokens):
                base_score *= 0.55
            elif not query_wants_modifier and ("segar" in core_tokens or "mentah" in core_tokens):
                base_score *= 1.15
            matching_substrings.append((base_score, dict(entry["row"])))

    if matching_substrings:
        matching_substrings.sort(key=lambda x: x[0], reverse=True)
        return matching_substrings[0][1]

    # 5. Fuzzy match ketat (cutoff 0.85) pada nama inti agar typo wajar terbantu tanpa false positive
    if len(query_lower) >= 4:
        core_to_row = {}
        for entry in catalog:
            ck = entry["core_name"]
            if ck not in core_to_row:
                core_to_row[ck] = entry["row"]
        matches = difflib.get_close_matches(query_lower, list(core_to_row.keys()), n=1, cutoff=0.85)
        if matches:
            return dict(core_to_row[matches[0]])

    return None

def fetch_open_food_facts(barcode: str):
    """
    Mengambil data nutrisi produk kemasan secara real-time dari Open Food Facts API v0.
    Dilengkapi timeout ketat 3 detik, konversi kJ -> kkal otomatis, dan antrean staging
    agar dapat ditinjau/diedit sebelum dipublikasikan ke katalog utama.
    """
    import urllib.request
    import json
    
    clean_bc = "".join(filter(str.isdigit, str(barcode)))
    if len(clean_bc) < 8:
        return None
        
    url = f"https://world.openfoodfacts.org/api/v0/product/{clean_bc}.json"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "NutrisiCerdas-MN/2.4 (https://nutrisi-cerdas.streamlit.app)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != 1:
                return None
            prod = data.get("product", {})
            nutr = prod.get("nutriments", {})
            
            raw_name = (
                prod.get("product_name_id")
                or prod.get("product_name")
                or prod.get("generic_name")
                or f"Produk Barcode {clean_bc}"
            ).strip()
            brand = (prod.get("brands") or "").split(",")[0].strip()
            if brand and brand.lower() not in raw_name.lower():
                full_name = f"{brand} - {raw_name}"
            else:
                full_name = raw_name
                
            # Konversi energi (prioritaskan kcal, fallback kJ / 4.184)
            kcal_100 = nutr.get("energy-kcal_100g") or nutr.get("energy-kcal")
            if kcal_100 is None:
                kj_val = nutr.get("energy-kj_100g") or nutr.get("energy_100g") or 0.0
                kcal_100 = round(float(kj_val) / 4.184, 1)
            else:
                kcal_100 = round(float(kcal_100), 1)
                
            p_100 = round(float(nutr.get("proteins_100g") or nutr.get("proteins") or 0.0), 1)
            f_100 = round(float(nutr.get("fat_100g") or nutr.get("fat") or 0.0), 1)
            c_100 = round(float(nutr.get("carbohydrates_100g") or nutr.get("carbohydrates") or 0.0), 1)
            fib_100 = round(float(nutr.get("fiber_100g") or nutr.get("fiber") or 0.0), 1)
            
            # Natrium di Open Food Facts umumnya dalam gram per 100g
            raw_sod = float(nutr.get("sodium_100g") or 0.0)
            sod_100 = round(raw_sod * 1000.0, 1) if raw_sod < 15.0 else round(raw_sod, 1)
            
            serv_size = prod.get("serving_size") or "1 kemasan (100g)"
            try:
                serv_weight = float(prod.get("serving_quantity") or 100.0)
                if serv_weight <= 0:
                    serv_weight = 100.0
            except:
                serv_weight = 100.0
                
            # Masukkan ke antrean staging (pending_foods) agar bisa diedit sebelum dipublikasikan
            try:
                from db_history import stage_pending_food
                stage_pending_food(
                    food_name=full_name,
                    category="Produk Kemasan (Open Food Facts)",
                    kcal_100=kcal_100,
                    p_100=p_100,
                    f_100=f_100,
                    c_100=c_100,
                    fib_100=fib_100,
                    sod_100=sod_100,
                    barcode=clean_bc,
                    serving_unit=serv_size,
                    serving_weight=serv_weight,
                    source_origin="Open Food Facts API"
                )
            except Exception:
                pass
                
            return {
                "food_name": full_name,
                "category": "Produk Kemasan (Open Food Facts)",
                "serving_unit": serv_size,
                "default_serving_weight": serv_weight,
                "bdd_rate": 100.0,
                "energy_kcal": kcal_100,
                "protein_g": p_100,
                "fat_g": f_100,
                "carb_g": c_100,
                "fiber_g": fib_100,
                "sodium_mg": sod_100,
                "barcode": clean_bc,
                "source_origin": "Open Food Facts API (Draft - Siap Diedit & Dipublikasi)"
            }
    except Exception:
        return None


def evaluate_nutri_grade(kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float = 0.0, sod_100: float = 0.0):
    """
    Menghitung Skor Nutri-Grade (A / B / C / D) dan Rambu Peringatan GGL Kemenkes RI
    berdasarkan kepadatan nutrisi per 100g/porsi.
    """
    score = 100
    badges = []
    
    # Penalti Kalori, Lemak, & Natrium
    if kcal_100 > 350:
        score -= 25
        badges.append(("🔴 Padat Kalori", "#ef4444"))
    elif kcal_100 > 220:
        score -= 10
        badges.append(("🟡 Kalori Sedang", "#f59e0b"))
    else:
        badges.append(("🟢 Rendah-Sedang Kalori", "#10b981"))
        
    if f_100 > 20.0:
        score -= 25
        badges.append(("🔴 Tinggi Lemak (>20g)", "#ef4444"))
    elif f_100 <= 5.0:
        score += 5
        badges.append(("🟢 Rendah Lemak", "#10b981"))
        
    if sod_100 > 400.0:
        score -= 20
        badges.append(("🔴 Tinggi Natrium/Garam", "#ef4444"))
        
    # Bonus Protein & Serat
    if p_100 >= 12.0:
        score += 15
        badges.append(("🟢 Tinggi Protein", "#10b981"))
    elif p_100 >= 6.0:
        score += 5
        
    if fib_100 >= 3.0:
        score += 10
        badges.append(("🟢 Kaya Serat Pangan", "#10b981"))
        
    if score >= 85:
        return {"grade": "A", "color": "#10b981", "label": "Sangat Sehat & Padat Gizi", "badges": badges}
    elif score >= 70:
        return {"grade": "B", "color": "#0284c7", "label": "Pilihan Baik & Seimbang", "badges": badges}
    elif score >= 50:
        return {"grade": "C", "color": "#f59e0b", "label": "Konsumsi Secukupnya", "badges": badges}
    else:
        return {"grade": "D", "color": "#ef4444", "label": "Batasi Porsi (Tinggi Kalori/Lemak/Garam)", "badges": badges}


def auto_learn_food(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float, sodium_100: float = 0.0, barcode: str = None, serving_unit: str = "porsi/buah", serving_weight: float = 100.0, auto_publish: bool = False):
    """
    Cara 1: Auto-Learning AI / Self-Expanding Database dengan Proteksi Moderasi.
    - Jika auto_publish=False (default): Masuk ke tabel staging (pending_foods) agar dapat
      ditinjau & diedit terlebih dahulu sebelum dipublikasikan (menghindari update mendadak).
    - Jika auto_publish=True: Langsung masuk ke tabel utama food_composition beserta nomor barcode.
    """
    clean_name = food_name.strip()
    if not clean_name or len(clean_name) < 2 or kcal_100 <= 0:
        return None
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        clean_bc = barcode.strip() if barcode else None
        if clean_bc:
            cur.execute("SELECT id, food_name FROM food_composition WHERE barcode = ? LIMIT 1", (clean_bc,))
            ex_bc = cur.fetchone()
            if ex_bc:
                conn.close()
                return ex_bc["food_name"]
                
        # Cek apakah nama ini persis sudah tersimpan sebelumnya
        cur.execute("SELECT id, food_name FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1", (clean_name,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return existing["food_name"]
            
        if not auto_publish:
            conn.close()
            from db_history import stage_pending_food
            stage_pending_food(
                food_name=clean_name.title(),
                category=category or "Pangan Olahan (Auto-Learn AI)",
                kcal_100=kcal_100,
                p_100=p_100,
                f_100=f_100,
                c_100=c_100,
                fib_100=fib_100,
                sod_100=sodium_100,
                barcode=clean_bc or "",
                serving_unit=serving_unit,
                serving_weight=serving_weight,
                source_origin="AI Auto-Learn"
            )
            return clean_name.title()
            
        # Buat kode unik otomatis jika dipublikasikan langsung
        import hashlib
        code_hash = hashlib.md5(clean_name.encode('utf-8')).hexdigest()[:6].upper()
        food_code = f"AUTO_{code_hash}"
        
        cur.execute("""
            INSERT INTO food_composition 
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg, barcode)
            VALUES (?, ?, ?, ?, ?, 100.0, ?, ?, ?, ?, ?, ?, ?)
        """, (
            food_code,
            clean_name.title(),
            category or "Pangan Olahan (Auto-Learn AI)",
            serving_unit,
            float(serving_weight),
            round(kcal_100, 1),
            round(p_100, 1),
            round(f_100, 1),
            round(c_100, 1),
            round(fib_100, 1),
            round(sodium_100, 1),
            clean_bc
        ))
        conn.commit()
        conn.close()
        return clean_name.title()
    except Exception as e:
        print(f"[AutoLearn] Gagal auto-insert {clean_name}: {e}")
        return None

def calculate_dish_nutrition(ai_components: list, portion_multiplier: float = 1.0, auto_learn: bool = True):
    """
    Menerima daftar komponen dari AI. Jika item tidak ada di database lokal,
    gunakan estimasi nutrisi per 100g yang dikirimkan oleh AI.
    Set auto_learn=False saat render interaktif slider/checkbox agar 0 penulisan DB berulang.
    """
    calculated_items = []
    totals = {
        "energy_kcal": 0.0,
        "protein_g": 0.0,
        "fat_g": 0.0,
        "carb_g": 0.0,
        "fiber_g": 0.0,
        "sodium_mg": 0.0,
        "total_weight_g": 0.0
    }
    
    for comp in ai_components:
        raw_name = comp.get("name", "")
        weight = float(comp.get("weight_g", 0)) * portion_multiplier
        
        is_override = bool(comp.get("custom_override"))
        match = None if is_override else find_best_match(raw_name)
        if match:
            factor = (weight * (match["bdd_rate"] / 100.0)) / 100.0
            
            kcal = round(match["energy_kcal"] * factor, 1)
            protein = round(match["protein_g"] * factor, 1)
            fat = round(match["fat_g"] * factor, 1)
            carb = round(match["carb_g"] * factor, 1)
            fiber = round(match["fiber_g"] * factor, 1)
            sodium = round(match["sodium_mg"] * factor, 1)
            
            item_res = {
                "input_name": raw_name,
                "tkpi_matched_name": match["food_name"],
                "category": match["category"],
                "weight_g": round(weight, 1),
                "energy_kcal": kcal,
                "protein_g": protein,
                "fat_g": fat,
                "carb_g": carb,
                "fiber_g": fiber,
                "sodium_mg": sodium
            }
        else:
            # Gunakan data nutrisi per 100g yang diekstrak langsung oleh AI atau koreksi manual user
            kcal_100 = float(comp.get("energy_kcal_per_100g", 0.0))
            p_100 = float(comp.get("protein_g_per_100g", 0.0))
            f_100 = float(comp.get("fat_g_per_100g", 0.0))
            c_100 = float(comp.get("carb_g_per_100g", 0.0))
            fib_100 = float(comp.get("fiber_g_per_100g", 0.0))
            sod_100 = float(comp.get("sodium_mg_per_100g", 0.0))
            
            # Auto-Learning: Simpan otomatis ke antrean staging jika hasil dari ekstraksi AI
            if kcal_100 > 0 and not is_override and auto_learn:
                auto_learn_food(raw_name, "Pangan Olahan (Auto-Learn AI)", kcal_100, p_100, f_100, c_100, fib_100, sod_100)
            
            factor = weight / 100.0
            item_res = {
                "input_name": raw_name,
                "tkpi_matched_name": comp.get("source_label") or f"(Auto-Learned AI: {raw_name.title()})",
                "category": "Pangan Olahan (Auto-Learn AI)",
                "weight_g": round(weight, 1),
                "energy_kcal": round(kcal_100 * factor, 1),
                "protein_g": round(p_100 * factor, 1),
                "fat_g": round(f_100 * factor, 1),
                "carb_g": round(c_100 * factor, 1),
                "fiber_g": round(fib_100 * factor, 1),
                "sodium_mg": round(sod_100 * factor, 1)
            }
            
        calculated_items.append(item_res)
        totals["total_weight_g"] += item_res["weight_g"]
        totals["energy_kcal"] += item_res["energy_kcal"]
        totals["protein_g"] += item_res["protein_g"]
        totals["fat_g"] += item_res["fat_g"]
        totals["carb_g"] += item_res["carb_g"]
        totals["fiber_g"] += item_res["fiber_g"]
        totals["sodium_mg"] += item_res["sodium_mg"]
        
    for k in totals:
        totals[k] = round(totals[k], 1)
        
    return {
        "items": calculated_items,
        "totals": totals
    }

if __name__ == "__main__":
    # Test simulasi: 1 Porsi Gado-Gado
    sample_gado_gado = [
        {"name": "Lontong", "weight_g": 100},
        {"name": "Sayuran rebus", "weight_g": 120},
        {"name": "Tahu goreng", "weight_g": 40},
        {"name": "Bumbu kacang", "weight_g": 50},
        {"name": "Telur rebus", "weight_g": 55},
        {"name": "Kerupuk", "weight_g": 15}
    ]
    res = calculate_dish_nutrition(sample_gado_gado)
    print("=== TEST ESTIMASI NUTRISI GADO-GADO (TKPI KEMENKES) ===")
    for it in res["items"]:
        print(f"- {it['input_name']} ({it['weight_g']}g) -> {it['energy_kcal']} kkal | P: {it['protein_g']}g | L: {it['fat_g']}g | K: {it['carb_g']}g")
    print("\nTOTAL GIZI 1 PORSI:")
    print(res["totals"])

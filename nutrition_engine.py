"""
Nutrition Calculator & Matcher Engine
Mencari padanan item hasil deteksi AI ke Database TKPI Kemenkes dan menghitung nilai gizi.
0 Token AI digunakan dalam perhitungan matematika ini.
"""

import sqlite3
import os
import difflib

DB_PATH = os.path.join(os.path.dirname(__file__), "tkpi_nutrition.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def find_best_match(query_name: str):
    """
    Mencari kecocokan terbaik di database TKPI dengan scoring prioritas:
    1. Special drinks (air, kopi, teh)
    2. Exact match
    3. Prefix / Word boundary match
    4. Substring match (diprioritaskan pada nama yang lebih ringkas & spesifik)
    5. Strict fuzzy match
    """
    conn = get_db_connection()
    cur = conn.cursor()
    rows = cur.execute("SELECT * FROM food_composition").fetchall()
    conn.close()
    
    query_lower = query_name.lower().strip()
    
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
    
    # 2. Cek exact match
    for row in rows:
        if query_lower == row["food_name"].lower():
            return dict(row)

    # 3. Cek apakah query ada di dalam nama makanan di DB, urutkan berdasarkan prioritas:
    # - Prioritaskan kata yang diawali dengan query (prefix)
    # - Beri penalti jika nama terlalu panjang dibanding query
    matching_substrings = []
    query_words = [w for w in query_lower.split() if len(w) >= 3]
    for row in rows:
        name_lower = row["food_name"].lower()
        if len(query_lower) >= 3 and query_lower in name_lower:
            starts_bonus = 2.0 if name_lower.startswith(query_lower) else 1.0
            score = (len(query_lower) / len(name_lower)) * starts_bonus
            matching_substrings.append((score, dict(row)))
        elif query_words and all(w in name_lower for w in query_words):
            score = sum(len(w) for w in query_words) / len(name_lower)
            matching_substrings.append((score, dict(row)))
            
    if matching_substrings:
        matching_substrings.sort(key=lambda x: x[0], reverse=True)
        return matching_substrings[0][1]
            
    # 4. Fuzzy match dengan batas kemiripan ketat (cutoff 0.70)
    names = [row["food_name"] for row in rows]
    matches = difflib.get_close_matches(query_name, names, n=1, cutoff=0.70)
    if matches:
        best_name = matches[0]
        for row in rows:
            if row["food_name"] == best_name:
                return dict(row)
                
    return None

def auto_learn_food(food_name: str, category: str, kcal_100: float, p_100: float, f_100: float, c_100: float, fib_100: float, sodium_100: float = 0.0):
    """
    Cara 1: Auto-Learning AI / Self-Expanding Database.
    Secara otomatis memasukkan bahan makanan baru hasil identifikasi AI yang belum ada di database lokal
    ke dalam tkpi_nutrition.db agar ke depannya menjadi 0 token dan dapat langsung dicari lokal.
    """
    clean_name = food_name.strip()
    if not clean_name or len(clean_name) < 2 or kcal_100 <= 0:
        return None
        
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Cek apakah nama ini persis sudah tersimpan sebelumnya
        cur.execute("SELECT id, food_name FROM food_composition WHERE LOWER(food_name) = LOWER(?) LIMIT 1", (clean_name,))
        existing = cur.fetchone()
        if existing:
            conn.close()
            return existing["food_name"]
            
        # Buat kode unik otomatis
        import time, hashlib
        code_hash = hashlib.md5(clean_name.encode('utf-8')).hexdigest()[:6].upper()
        food_code = f"AUTO_{code_hash}"
        
        cur.execute("""
            INSERT INTO food_composition 
            (food_code, food_name, category, serving_unit, default_serving_weight, bdd_rate, energy_kcal, protein_g, fat_g, carb_g, fiber_g, sodium_mg)
            VALUES (?, ?, ?, 'porsi/buah', 100.0, 100.0, ?, ?, ?, ?, ?, ?)
        """, (
            food_code,
            clean_name.title(),
            category or "Pangan Olahan (Auto-Learn AI)",
            round(kcal_100, 1),
            round(p_100, 1),
            round(f_100, 1),
            round(c_100, 1),
            round(fib_100, 1),
            round(sodium_100, 1)
        ))
        conn.commit()
        conn.close()
        return clean_name.title()
    except Exception as e:
        print(f"[AutoLearn] Gagal auto-insert {clean_name}: {e}")
        return None

def calculate_dish_nutrition(ai_components: list, portion_multiplier: float = 1.0):
    """
    Menerima daftar komponen dari AI. Jika item tidak ada di database lokal,
    gunakan estimasi nutrisi per 100g yang dikirimkan oleh AI.
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
        
        match = find_best_match(raw_name)
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
            # Gunakan data nutrisi per 100g yang diekstrak langsung oleh AI
            kcal_100 = float(comp.get("energy_kcal_per_100g", 0.0))
            p_100 = float(comp.get("protein_g_per_100g", 0.0))
            f_100 = float(comp.get("fat_g_per_100g", 0.0))
            c_100 = float(comp.get("carb_g_per_100g", 0.0))
            fib_100 = float(comp.get("fiber_g_per_100g", 0.0))
            sod_100 = float(comp.get("sodium_mg_per_100g", 0.0))
            
            # Auto-Learning: Simpan otomatis ke database lokal untuk pencarian masa depan (0 token)
            if kcal_100 > 0:
                auto_learn_food(raw_name, "Pangan Olahan (Auto-Learn AI)", kcal_100, p_100, f_100, c_100, fib_100, sod_100)
            
            factor = weight / 100.0
            item_res = {
                "input_name": raw_name,
                "tkpi_matched_name": f"(Auto-Learned AI: {raw_name.title()})",
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

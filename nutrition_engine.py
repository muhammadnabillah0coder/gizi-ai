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
    Mencari kecocokan terbaik di database TKPI menggunakan kombinasi
    SQL LIKE dan string similarity (difflib).
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Cek exact / partial match di SQL
    rows = cur.execute("SELECT * FROM food_composition").fetchall()
    conn.close()
    
    query_lower = query_name.lower().strip()
    
    # Cek kecocokan substring langsung
    for row in rows:
        name_lower = row["food_name"].lower()
        if query_lower in name_lower or name_lower in query_lower:
            return dict(row)
            
    # 2. Fuzzy match dengan skor kemiripan tertinggi
    names = [row["food_name"] for row in rows]
    matches = difflib.get_close_matches(query_name, names, n=1, cutoff=0.3)
    if matches:
        best_name = matches[0]
        for row in rows:
            if row["food_name"] == best_name:
                return dict(row)
                
    return None

def calculate_dish_nutrition(ai_components: list, portion_multiplier: float = 1.0):
    """
    Menerima daftar komponen dari AI:
    [{"name": "bumbu kacang", "weight_g": 50}, ...]
    dan menghitung total makronutrien berdasarkan data lab TKPI per 100g.
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
            # Fallback jika bahan tidak ada di database: estimasi rata-rata
            kcal = round(weight * 1.5, 1)
            protein = round(weight * 0.05, 1)
            fat = round(weight * 0.05, 1)
            carb = round(weight * 0.20, 1)
            item_res = {
                "input_name": raw_name,
                "tkpi_matched_name": f"(Estimasi umum: {raw_name})",
                "category": "Lainnya",
                "weight_g": round(weight, 1),
                "energy_kcal": kcal,
                "protein_g": protein,
                "fat_g": fat,
                "carb_g": carb,
                "fiber_g": 0.0,
                "sodium_mg": 0.0
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

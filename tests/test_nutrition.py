"""
Unit Test Nutrisi Cerdas: Memverifikasi akurasi kalkulator nutrisi deterministik berbasis data lab TKPI Kemenkes RI.
"""

import sys
import os
import unittest
import sqlite3
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nutrition_engine import (
    calculate_dish_nutrition,
    find_best_match,
    evaluate_nutri_grade,
    fetch_open_food_facts,
    DB_PATH
)
from db_history import (
    init_user_history_tables,
    stage_pending_food,
    get_pending_foods,
    publish_food_to_catalog,
    reject_pending_food
)

def test_find_best_match_gado_gado():
    match = find_best_match("Lontong")
    assert match is not None
    assert "Lontong" in match["food_name"]
    assert match["energy_kcal"] > 100

def test_nutrition_calculation_accuracy():
    sample_items = [
        {"name": "Nasi putih", "weight_g": 100},
        {"name": "Telur ayam rebus", "weight_g": 55}
    ]
    res = calculate_dish_nutrition(sample_items, portion_multiplier=1.0)
    totals = res["totals"]
    
    # Nasi 100g = 130 kkal
    # Telur rebus 55g (BDD 89%) = 55 * 0.89 = 48.95g -> (48.95/100)*155 = ~75.8 kkal
    # Total kkal berkisar antara 200 - 210 kkal
    assert 200.0 <= totals["energy_kcal"] <= 215.0
    assert totals["protein_g"] > 8.0 # Nasi ~2.4g + Telur ~6.1g
    assert totals["fat_g"] > 4.0

def test_portion_multiplier():
    sample_items = [{"name": "Nasi putih", "weight_g": 100}]
    
    res_normal = calculate_dish_nutrition(sample_items, portion_multiplier=1.0)
    res_jumbo = calculate_dish_nutrition(sample_items, portion_multiplier=1.5)
    
    assert round(res_jumbo["totals"]["energy_kcal"], 1) == round(res_normal["totals"]["energy_kcal"] * 1.5, 1)

def test_nutri_grade_evaluation():
    # Grade A: rendah kalori, tinggi serat & protein, rendah natrium & lemak
    grade_a = evaluate_nutri_grade(kcal_100=90, p_100=12, f_100=1.5, c_100=10, fib_100=4.0, sod_100=50)
    assert grade_a["grade"] in ("A", "B")
    assert "color" in grade_a and "badges" in grade_a

    # Grade D: tinggi kalori, tinggi lemak & natrium
    grade_d = evaluate_nutri_grade(kcal_100=550, p_100=3, f_100=32.0, c_100=62, fib_100=0.5, sod_100=950)
    assert grade_d["grade"] in ("C", "D")
    assert len(grade_d["badges"]) >= 1

def test_staging_edit_before_publish_workflow():
    init_user_history_tables()
    test_name = "Uji Coba Makanan Staging 999"
    test_barcode = "9990001112223"
    
    # 1. Stage ke antrean pending_foods
    pid_created = stage_pending_food(
        food_name=test_name,
        category="Produk Kemasan Uji",
        kcal_100=250.0,
        p_100=10.0,
        f_100=8.0,
        c_100=35.0,
        fib_100=2.5,
        sod_100=180.0,
        barcode=test_barcode,
        serving_unit="1 bungkus",
        serving_weight=75.0,
        source_origin="UnitTest",
        submitted_by="tester"
    )
    assert pid_created is not None

    # 2. Pastikan masuk di daftar pending
    pendings = get_pending_foods("pending")
    matched = [p for p in pendings if p["food_name"] == test_name]
    assert len(matched) == 1
    pid = matched[0]["id"]

    # 3. Publikasikan dengan koreksi/edit nilai gizi (misal: energi diedit jadi 265 kkal)
    ok_pub = publish_food_to_catalog(
        food_name=test_name,
        category="Produk Kemasan Uji",
        kcal_100=265.0,
        p_100=11.0,
        f_100=8.0,
        c_100=35.0,
        fib_100=3.0,
        sod_100=180.0,
        barcode=test_barcode,
        serving_unit="1 bungkus",
        serving_weight=75.0,
        pending_id=pid
    )
    assert ok_pub is True

    # 4. Pastikan bisa dicari via barcode di katalog utama
    found = find_best_match(test_barcode)
    assert found is not None
    assert found["energy_kcal"] == 265.0

    # Bersihkan data uji coba dari DB
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM food_composition WHERE food_name = ? OR barcode = ?", (test_name, test_barcode))
    c.execute("DELETE FROM pending_foods WHERE id = ? OR food_name = ?", (pid, test_name))
    conn.commit()
    conn.close()

def test_open_food_facts_invalid_barcode_graceful():
    # Barcode pendek / tidak valid tidak boleh crash
    assert fetch_open_food_facts("123") is None
    assert fetch_open_food_facts("0000000000000") is None

def test_sate_ayam_skin_split_no_double_fat():
    m_lean = find_best_match("Daging ayam tanpa kulit")
    m_skin = find_best_match("Kulit ayam panggang")
    assert m_lean is not None and "tanpa kulit" in m_lean["food_name"].lower()
    assert m_skin is not None and "kulit ayam" in m_skin["food_name"].lower()

    # Simulasi realistis 20 tusuk sate ayam warung + kulit + bumbu kacang + kecap
    res = calculate_dish_nutrition([
        {"name": "Daging ayam tanpa kulit", "weight_g": 200},
        {"name": "Kulit ayam panggang", "weight_g": 70},
        {"name": "Bumbu kacang gado-gado / sate", "weight_g": 70},
        {"name": "Kecap manis", "weight_g": 20},
    ], portion_multiplier=1.0, auto_learn=False)
    tot = res["totals"]
    assert 800.0 <= tot["energy_kcal"] <= 1150.0, f"Kalori sate tidak wajar: {tot['energy_kcal']}"
    assert 35.0 <= tot["fat_g"] <= 60.0, f"Lemak terhitung ganda: {tot['fat_g']}"
    assert tot["protein_g"] >= 65.0

def test_retail_barcode_serving_math_and_tkpi_physics_integrity():
    """Memverifikasi 4 barcode sampel UI & konsistensi fisika gizi pada food_composition."""
    sample_barcodes = [
        ("8998866200231", "Ultra Milk", 160.0),
        ("089686010921", "Indomie Mi Goreng", 390.0),
        ("3017620422003", "Nutella", 80.0),
        ("7622210449283", "Oreo", 140.0),
    ]
    for bc, expected_name_sub, expected_pack_kcal in sample_barcodes:
        matched = find_best_match(bc)
        assert matched is not None, f"Barcode {bc} gagal ditemukan di katalog lokal."
        assert expected_name_sub.lower() in matched["food_name"].lower(), (
            f"Barcode {bc} mengembalikan {matched['food_name']}, bukan {expected_name_sub}"
        )
        pack_w = float(matched.get("default_serving_weight") or 100.0)
        res = calculate_dish_nutrition([
            {
                "name": matched["food_name"],
                "weight_g": pack_w,
                "energy_kcal_per_100g": float(matched["energy_kcal"]),
                "protein_g_per_100g": float(matched["protein_g"]),
                "fat_g_per_100g": float(matched["fat_g"]),
                "carb_g_per_100g": float(matched["carb_g"]),
                "fiber_g_per_100g": float(matched.get("fiber_g") or 0.0),
                "sodium_mg_per_100g": float(matched.get("sodium_mg") or 0.0),
                "custom_override": True,
            }
        ], portion_multiplier=1.0, auto_learn=False)
        calc_kcal = float(res["totals"]["energy_kcal"])
        assert abs(calc_kcal - expected_pack_kcal) <= 0.5, (
            f"Kalori kemasan {bc} ({matched['food_name']}) meleset: {calc_kcal} vs {expected_pack_kcal}"
        )

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    pfc_over = cur.execute(
        "SELECT COUNT(*) FROM food_composition WHERE (COALESCE(protein_g, 0) + COALESCE(fat_g, 0) + COALESCE(carb_g, 0)) > 103.0"
    ).fetchone()[0]
    fiber_over = cur.execute(
        "SELECT COUNT(*) FROM food_composition WHERE COALESCE(fiber_g, 0) > COALESCE(carb_g, 0)"
    ).fetchone()[0]
    kcal_over = cur.execute(
        "SELECT COUNT(*) FROM food_composition WHERE COALESCE(energy_kcal, 0) > 905.0"
    ).fetchone()[0]
    conn.close()

    assert pfc_over == 0, f"Ditemukan {pfc_over} baris dengan P+F+C > 103g per 100g!"
    assert fiber_over == 0, f"Ditemukan {fiber_over} baris dengan fiber_g > carb_g!"
    assert kcal_over == 0, f"Ditemukan {kcal_over} baris dengan energy_kcal > 905 kkal!"

class TestNutritionSuite(unittest.TestCase):
    def test_all(self):
        test_find_best_match_gado_gado()
        test_nutrition_calculation_accuracy()
        test_portion_multiplier()
        test_nutri_grade_evaluation()
        test_staging_edit_before_publish_workflow()
        test_open_food_facts_invalid_barcode_graceful()
        test_sate_ayam_skin_split_no_double_fat()
        test_retail_barcode_serving_math_and_tkpi_physics_integrity()

if __name__ == "__main__":
    print("Menjalankan unit test...")
    test_find_best_match_gado_gado()
    test_nutrition_calculation_accuracy()
    test_portion_multiplier()
    test_nutri_grade_evaluation()
    test_staging_edit_before_publish_workflow()
    test_open_food_facts_invalid_barcode_graceful()
    test_sate_ayam_skin_split_no_double_fat()
    test_retail_barcode_serving_math_and_tkpi_physics_integrity()
    print("Semua unit test lolos 100%!")

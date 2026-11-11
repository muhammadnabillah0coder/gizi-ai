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

class TestNutritionSuite(unittest.TestCase):
    def test_all(self):
        test_find_best_match_gado_gado()
        test_nutrition_calculation_accuracy()
        test_portion_multiplier()
        test_nutri_grade_evaluation()
        test_staging_edit_before_publish_workflow()
        test_open_food_facts_invalid_barcode_graceful()

if __name__ == "__main__":
    print("Menjalankan unit test...")
    test_find_best_match_gado_gado()
    test_nutrition_calculation_accuracy()
    test_portion_multiplier()
    test_nutri_grade_evaluation()
    test_staging_edit_before_publish_workflow()
    test_open_food_facts_invalid_barcode_graceful()
    print("Semua unit test lolos 100%!")

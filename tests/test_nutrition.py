"""
Unit Test: Memverifikasi akurasi perhitungan gizi deterministik berbasis data lab TKPI Kemenkes.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from nutrition_engine import calculate_dish_nutrition, find_best_match

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

if __name__ == "__main__":
    print("Menjalankan unit test...")
    test_find_best_match_gado_gado()
    test_nutrition_calculation_accuracy()
    test_portion_multiplier()
    print("Semua unit test lolos 100%!")

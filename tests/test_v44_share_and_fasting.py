"""
Suite Pengujian Regresi v4.4.0 Nutrisi Cerdas:
1. Generator Kartu Visual IG Story / Status WA (share_card.py): PNG 1080x1920 valid untuk tema Terang & Gelap, penuh maupun kosong.
2. Persistensi Mode Puasa (fasting_mode) di db_history.py (Normal, Puasa Sunnah / Ramadan, Intermittent Fasting 16:8).
3. Integrasi AppTest: Mode Puasa menampilkan pola air 2-4-2 & sesi Sahur/Takjil, serta tombol Kartu IG Story / WA (PNG) berjalan tanpa error.
"""

import io
import os
import sqlite3
import sys
import time
import unittest
import uuid
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history
import share_card


class TestV44ShareCardAndFasting(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.test_uid = f"v44_{uuid.uuid4().hex[:8]}@example.com"
        ok, _ = db_history.register_user(self.test_uid, "Pengguna Puasa", "1234", bb=68.0)
        self.assertTrue(ok)
        self.tok = db_history.create_session_token(self.test_uid)

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
            cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (self.test_uid,))
        conn.commit()
        conn.close()

    def test_01_share_card_png_1080x1920_light_dark_and_empty(self):
        sample_meals = [
            {"dish_name": "Nasi Putih + Ayam Bakar Dada", "meal_type": "Sahur", "energy_kcal": 385.0},
            {"dish_name": "3 Butir Kurma + Air Putih", "meal_type": "Takjil & Buka", "energy_kcal": 95.0},
            {"dish_name": "Soto Ayam Kuah Bening", "meal_type": "Makan Utama", "energy_kcal": 395.0},
        ]
        totals = {"energy_kcal": 875.0, "protein_g": 56.0, "fat_g": 21.0, "carb_g": 110.0, "fiber_g": 9.5, "sugar_g": 18.0, "sodium_mg": 1050.0, "count": 3}
        targets = {"protein_g": 110.0, "fat_g": 62.0, "carb_g": 250.0, "fiber_g": 25.0, "sugar_g": 50.0, "sodium_mg": 2000.0}

        for style in ("light", "dark"):
            t0 = time.perf_counter()
            png_bytes = share_card.generate_daily_share_card_png(
                display_name="Pengguna Puasa",
                date_label="Kam, 26 Nov 2026",
                focus_goal="Diet Sehat",
                fasting_mode="Puasa Sunnah / Ramadan",
                today_kcal=875.0,
                target_kcal=2000.0,
                totals=totals,
                macro_targets=targets,
                water_data={"glasses": 6, "target": 9},
                streak_days=5,
                today_meals=sample_meals,
                style=style,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.assertLess(elapsed_ms, 2000.0, f"Render kartu {style} terlalu lambat: {elapsed_ms:.0f}ms")
            self.assertGreater(len(png_bytes), 10_000)

            im = Image.open(io.BytesIO(png_bytes))
            self.assertEqual(im.format, "PNG")
            self.assertEqual(im.size, (1080, 1920))

        # Kasus kosong (0 menu) & melebihi target (>105%) tidak boleh crash
        empty_png = share_card.generate_daily_share_card_png(
            display_name="Tamu",
            date_label="Kam, 26 Nov 2026",
            focus_goal="Diet Sehat",
            fasting_mode="Normal",
            today_kcal=2400.0,
            target_kcal=2000.0,
            totals={"count": 0},
            macro_targets=targets,
            water_data={"glasses": 0, "target": 8},
            streak_days=0,
            today_meals=[],
            style="light",
        )
        im_empty = Image.open(io.BytesIO(empty_png))
        self.assertEqual(im_empty.size, (1080, 1920))

    def test_02_fasting_mode_persistence_and_validation(self):
        db_history.update_user_preferences(self.test_uid, fasting_mode="Puasa Sunnah / Ramadan")
        u1 = db_history.get_or_create_user(self.test_uid)
        self.assertEqual(u1["fasting_mode"], "Puasa Sunnah / Ramadan")

        db_history.update_user_preferences(self.test_uid, fasting_mode="Intermittent Fasting 16:8")
        u2 = db_history.get_or_create_user(self.test_uid)
        self.assertEqual(u2["fasting_mode"], "Intermittent Fasting 16:8")

        # Nilai tidak dikenal harus diabaikan dengan aman
        db_history.update_user_preferences(self.test_uid, fasting_mode="Mode Aneh Invalid")
        u3 = db_history.get_or_create_user(self.test_uid)
        self.assertEqual(u3["fasting_mode"], "Intermittent Fasting 16:8")

    def test_03_apptest_fasting_242_guide_and_share_card_download(self):
        from streamlit.testing.v1 import AppTest

        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")
        db_history.update_user_preferences(self.test_uid, fasting_mode="Puasa Sunnah / Ramadan")
        db_history.log_meal(
            self.test_uid,
            "Nasi + Ayam Bakar Sahur",
            {"energy_kcal": 420.0, "protein_g": 31.0, "fat_g": 9.0, "carb_g": 52.0, "fiber_g": 2.5, "sodium_mg": 380.0, "sugar_g": 3.0},
            meal_type="Sahur",
            log_date=today_str,
            tz_offset=8,
        )
        db_history.log_water_intake(self.test_uid, 4, tz_offset=8)

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        at = AppTest.from_file(app_path, default_timeout=30)
        at.query_params["u"] = self.test_uid
        at.query_params["s"] = self.tok
        at.run()
        self.assertEqual(len(at.exception), 0, f"Fasting + Share Card UI crash: {at.exception}")

        all_captions = "\n".join(c.value for c in at.caption)
        self.assertIn("2-4-2", all_captions)
        self.assertIn("Berbuka 2/2", all_captions)
        all_md = "\n".join(m.value for m in at.markdown)
        self.assertIn("Puasa Sunnah / Ramadan", all_md)
        self.assertIn("Sahur", all_md)


if __name__ == "__main__":
    unittest.main()

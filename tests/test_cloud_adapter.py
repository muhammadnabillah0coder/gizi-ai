"""
Unit Test untuk Dual-Backend Cloud Adapter (Supabase PostgreSQL / SQLite),
Fungsi Anti-Double (update_meal_log, scale_meal_log_portion, remove_duplicate_meals_for_date),
Frequent Meals, Copy Yesterday, dan Pencocokan TKPI Gen-2.
"""

import os
import sys
import uuid
import sqlite3
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history
from nutrition_engine import find_best_match, compute_macro_targets


class TestCloudAdapterAndV4(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.test_uid = f"test_v4_{uuid.uuid4().hex[:8]}@example.com"
        db_history.register_user(self.test_uid, "Tester v4", "1234", bb=68.0)

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
            cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (self.test_uid,))
        conn.commit()
        conn.close()

    def test_parse_database_url_and_pg_translators(self):
        uri = "postgresql://postgres.proj123:p%40ss%23word@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
        cfg = db_history.parse_database_url(uri)
        self.assertEqual(cfg["host"], "aws-0-ap-southeast-1.pooler.supabase.com")
        self.assertEqual(cfg["port"], 5432)
        self.assertEqual(cfg["user"], "postgres.proj123")
        self.assertEqual(cfg["password"], "p@ss#word")
        self.assertEqual(cfg["database"], "postgres")
        self.assertTrue(cfg["use_ssl"])

        with self.assertRaises(ValueError):
            db_history.parse_database_url("mysql://user:pass@localhost/db")

        sql = "SELECT * FROM meal_logs WHERE dish_name = 'Kenapa?' AND user_id = ? AND meal_type = ?"
        pg_sql = db_history._translate_qmark_to_pg(sql)
        self.assertEqual(
            pg_sql,
            "SELECT * FROM meal_logs WHERE dish_name = 'Kenapa?' AND user_id = %s AND meal_type = %s",
        )

        ins_meal, ret1 = db_history._inject_returning_id("INSERT INTO meal_logs (user_id) VALUES (%s)")
        self.assertTrue(ret1)
        self.assertTrue(ins_meal.endswith("RETURNING id"))

        ins_meta, ret2 = db_history._inject_returning_id("INSERT INTO app_meta (meta_key, meta_value) VALUES (%s, %s)")
        self.assertFalse(ret2)
        self.assertNotIn("RETURNING id", ins_meta)

    def test_anti_double_update_and_portion_scaling(self):
        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")
        logged = db_history.log_meal(
            user_id=self.test_uid,
            dish_name="Pepaya Potong",
            totals={"energy_kcal": 280.0, "protein_g": 2.0, "fat_g": 0.4, "carb_g": 68.0, "fiber_g": 8.0, "sodium_mg": 12.0},
            multiplier=1.0,
            meal_type="Sarapan",
            log_date=today_str,
            tz_offset=8,
        )
        log_id = logged["id"]

        # Ubah porsi 1.0x -> 0.25x & pindah ke Camilan pada baris yang sama (tanpa mendobel)
        updated = db_history.scale_meal_log_portion(log_id, self.test_uid, new_multiplier=0.25, new_meal_type="Camilan")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["meal_type"], "Camilan")
        self.assertEqual(updated["energy_kcal"], 70.0)

        stats = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats["today_totals"]["count"], 1, "Update catatan tidak boleh membuat baris duplikat")
        self.assertEqual(stats["today_totals"]["energy_kcal"], 70.0)
        self.assertEqual(stats["today_meals"][0]["portion_multiplier"], 0.25)

    def test_duplicate_cleanup_frequent_and_copy_yesterday(self):
        today_dt = db_history.get_local_now(8).date()
        today_str = today_dt.strftime("%Y-%m-%d")
        yest_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

        # Simulasi catatan ganda seperti kasus Bingka Pisang x2 & Pepaya Potong x3
        db_history.log_meal(self.test_uid, "Bingka Pisang", {"energy_kcal": 2196.4, "protein_g": 20, "fat_g": 40, "carb_g": 400, "fiber_g": 4}, meal_type="Sarapan", log_date=today_str, tz_offset=8)
        db_history.log_meal(self.test_uid, "Bingka Pisang", {"energy_kcal": 219.6, "protein_g": 2, "fat_g": 4, "carb_g": 40, "fiber_g": 0.4}, meal_type="Camilan", log_date=today_str, tz_offset=8)
        db_history.log_meal(self.test_uid, "Pepaya Potong", {"energy_kcal": 280.0, "protein_g": 2, "fat_g": 0.4, "carb_g": 68, "fiber_g": 8}, meal_type="Sarapan", log_date=today_str, tz_offset=8)
        db_history.log_meal(self.test_uid, "Pepaya Potong", {"energy_kcal": 210.0, "protein_g": 1.5, "fat_g": 0.3, "carb_g": 51, "fiber_g": 6}, meal_type="Sarapan", log_date=today_str, tz_offset=8)
        db_history.log_meal(self.test_uid, "Pepaya Potong", {"energy_kcal": 70.0, "protein_g": 0.5, "fat_g": 0.1, "carb_g": 17, "fiber_g": 2}, meal_type="Camilan", log_date=today_str, tz_offset=8)

        removed = db_history.remove_duplicate_meals_for_date(self.test_uid, today_str)
        self.assertEqual(removed, 3)

        stats_after = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_after["today_totals"]["count"], 2)
        names_left = {m["dish_name"]: m["energy_kcal"] for m in stats_after["today_meals"]}
        self.assertEqual(names_left["Bingka Pisang"], 219.6)
        self.assertEqual(names_left["Pepaya Potong"], 70.0)

        # Tambah menu kemarin & uji copy_meals_from_date
        db_history.log_meal(self.test_uid, "Soto Ayam", {"energy_kcal": 350.0, "protein_g": 20, "fat_g": 10, "carb_g": 42, "fiber_g": 2}, meal_type="Makan Siang", log_date=yest_str, tz_offset=8)
        copied = db_history.copy_meals_from_date(self.test_uid, yest_str, today_str, tz_offset=8)
        self.assertEqual(copied, 1)
        # Panggil kedua kali harus idempoten (0 copied)
        copied_again = db_history.copy_meals_from_date(self.test_uid, yest_str, today_str, tz_offset=8)
        self.assertEqual(copied_again, 0)

        freq = db_history.get_frequent_meals(self.test_uid, limit=5)
        self.assertGreaterEqual(len(freq), 3)

    def test_tkpi_gen2_matching_and_macro_targets(self):
        m_sugar = find_best_match("Gula pasir")
        self.assertIsNotNone(m_sugar)
        self.assertNotIn("Gulai", m_sugar["food_name"])
        self.assertIn("Gula", m_sugar["food_name"])

        m_banana = find_best_match("Pisang")
        self.assertIsNotNone(m_banana)
        self.assertNotIn("goreng", m_banana["food_name"].lower())

        m_egg = find_best_match("Telur")
        self.assertIsNotNone(m_egg)
        self.assertNotIn("balado", m_egg["food_name"].lower())

        m_papaya = find_best_match("Pepaya Potong")
        self.assertIsNotNone(m_papaya)
        self.assertIn("Pepaya", m_papaya["food_name"])

        targets_ht = compute_macro_targets(2000.0, "Kendali Natrium (Hipertensi)")
        self.assertEqual(targets_ht["sodium_mg"], 1500.0)
        self.assertGreater(targets_ht["protein_g"], 90.0)

    def test_dict_row_pg_ddl_and_custom_override(self):
        from decimal import Decimal
        from datetime import datetime
        from unittest.mock import MagicMock
        from nutrition_engine import calculate_dish_nutrition

        row = db_history._DictRow(
            ["user_id", "energy_kcal", "logged_at"],
            ["nabillah", Decimal("205.5"), datetime(2026, 11, 18, 8, 15, 0)],
        )
        self.assertEqual(row["user_id"], "nabillah")
        self.assertEqual(row[1], 205.5)
        self.assertIsInstance(row["energy_kcal"], float)
        self.assertEqual(row["logged_at"], "2026-11-18 08:15:00")
        self.assertEqual(dict(row)["energy_kcal"], 205.5)

        # Uji DDL PostgreSQL menghasilkan SERIAL PRIMARY KEY & ADD COLUMN IF NOT EXISTS
        executed_sql = []
        fake_conn = MagicMock()
        fake_conn.backend = "postgres"
        fake_cur = MagicMock()
        fake_cur.execute.side_effect = lambda sql, params=(): executed_sql.append(sql)
        db_history._create_tables_on_cursor(fake_conn, fake_cur)
        joined = "\n".join(executed_sql)
        self.assertIn("SERIAL PRIMARY KEY", joined)
        self.assertIn("ADD COLUMN IF NOT EXISTS", joined)
        self.assertIn("food_catalog_additions", joined)

        # Uji custom_override tidak tertimpa nilai TKPI "Bingka"
        ovr_res = calculate_dish_nutrition(
            [{"name": "Bingka", "weight_g": 100.0, "energy_kcal_per_100g": 185.0, "protein_g_per_100g": 4.0, "fat_g_per_100g": 6.0, "carb_g_per_100g": 28.0, "custom_override": True}],
            portion_multiplier=0.5,
        )
        self.assertEqual(ovr_res["totals"]["energy_kcal"], 92.5)

        # Tanpa custom_override, 1 potong sedang Bingka (75g) = ~204.8 kkal (bukan 2196 kkal!)
        slice_res = calculate_dish_nutrition([{"name": "Bingka Pisang", "weight_g": 75.0}], portion_multiplier=1.0)
        self.assertAlmostEqual(slice_res["totals"]["energy_kcal"], 204.8, delta=1.0)


if __name__ == "__main__":
    unittest.main()

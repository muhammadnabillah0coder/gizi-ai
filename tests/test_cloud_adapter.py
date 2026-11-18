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
        self.assertFalse(cfg["ssl_verify"])

        cfg_strict = db_history.parse_database_url(f"{uri}?sslmode=verify-full")
        self.assertTrue(cfg_strict["use_ssl"])
        self.assertTrue(cfg_strict["ssl_verify"])

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

    def test_dashboard_bundle_parity(self):
        today_dt = db_history.get_local_now(8).date()
        today_str = today_dt.strftime("%Y-%m-%d")
        yest_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

        db_history.log_meal(self.test_uid, "Nasi Goreng", {"energy_kcal": 420.0, "protein_g": 12.0, "fat_g": 14.0, "carb_g": 60.0, "fiber_g": 2.0}, meal_type="Sarapan", log_date=yest_str, tz_offset=8)
        db_history.log_meal(self.test_uid, "Soto Ayam", {"energy_kcal": 310.0, "protein_g": 19.0, "fat_g": 9.0, "carb_g": 38.0, "fiber_g": 1.8}, meal_type="Makan Siang", log_date=today_str, tz_offset=8)
        db_history.log_water_intake(self.test_uid, 2, tz_offset=8)
        db_history.log_weight_entry(self.test_uid, 67.4, tz_offset=8, recorded_date=today_str)

        bundle = db_history.get_dashboard_bundle(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(bundle["scan_status"], db_history.get_user_scan_status(self.test_uid, tz_offset=8))
        self.assertEqual(bundle["stats"], db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8))
        self.assertEqual(bundle["streak_days"], db_history.get_logging_streak(self.test_uid, tz_offset=8))
        self.assertEqual(bundle["water_data"], db_history.get_water_intake(self.test_uid, tz_offset=8))
        self.assertEqual(bundle["weight_history"], db_history.get_weight_history(self.test_uid, limit=30))
        self.assertEqual(bundle["frequent_meals"], db_history.get_frequent_meals(self.test_uid, limit=6))

    def test_auto_learn_false_and_catalog_cache_invalidation(self):
        from unittest.mock import patch
        import nutrition_engine

        with patch("nutrition_engine.auto_learn_food") as mock_learn:
            res = nutrition_engine.calculate_dish_nutrition(
                [{
                    "name": "Menu Misterius Interaktif Xyz",
                    "weight_g": 100.0,
                    "energy_kcal_per_100g": 180.0,
                    "protein_g_per_100g": 6.0,
                    "fat_g_per_100g": 5.0,
                    "carb_g_per_100g": 26.0,
                }],
                portion_multiplier=0.5,
                auto_learn=False,
            )
            mock_learn.assert_not_called()
            self.assertEqual(res["totals"]["energy_kcal"], 90.0)

        first_catalog = nutrition_engine._get_cached_food_catalog()
        second_catalog = nutrition_engine._get_cached_food_catalog()
        self.assertIs(first_catalog, second_catalog)

        unique_food = f"Uji Katalog Cache {uuid.uuid4().hex[:6]}"
        try:
            db_history.publish_food_to_catalog(
                food_name=unique_food,
                category="Uji Unit",
                kcal_100=123.0,
                p_100=4.0,
                f_100=3.0,
                c_100=20.0,
                fib_100=1.0,
            )
            matched = nutrition_engine.find_best_match(unique_food)
            self.assertIsNotNone(matched)
            self.assertEqual(matched["food_name"], unique_food)
        finally:
            conn = sqlite3.connect(db_history.DB_PATH)
            conn.execute("DELETE FROM food_composition WHERE food_name = ?", (unique_food,))
            conn.execute("DELETE FROM food_catalog_additions WHERE food_name = ?", (unique_food,))
            conn.commit()
            conn.close()
            nutrition_engine.invalidate_food_catalog_cache()

    def test_pg_pool_acquire_release_reuse(self):
        from unittest.mock import MagicMock, patch

        db_history.close_all_pooled_connections()
        mock_raws = [MagicMock(), MagicMock()]
        test_uri = "postgresql://user:pass@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"

        with patch("db_history._open_pg_raw", side_effect=mock_raws) as mock_open:
            k1, c1 = db_history._acquire_pg_connection(test_uri)
            self.assertEqual(mock_open.call_count, 1)
            db_history._release_pg_connection(k1, c1, healthy=True)

            k2, c2 = db_history._acquire_pg_connection(test_uri)
            self.assertIs(c2, c1, "Koneksi pool sehat wajib dipakai ulang tanpa handshake ulang")
            self.assertEqual(mock_open.call_count, 1)

            db_history._release_pg_connection(k2, c2, healthy=False)
            _, c3 = db_history._acquire_pg_connection(test_uri)
            self.assertIsNot(c3, c1)
            self.assertEqual(mock_open.call_count, 2)

        db_history.close_all_pooled_connections()

    def test_module_mtime_and_sync_recovers_stale_module(self):
        import ast
        import importlib
        import types
        from unittest.mock import patch

        self.assertTrue(hasattr(db_history, "_MODULE_MTIME"))
        self.assertTrue(hasattr(nutrition_engine_mod := sys.modules["nutrition_engine"], "_MODULE_MTIME"))
        self.assertGreater(db_history._MODULE_MTIME, 0.0)
        self.assertGreater(nutrition_engine_mod._MODULE_MTIME, 0.0)

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, "r", encoding="utf-8") as fh:
            app_src = fh.read()
        tree = ast.parse(app_src)
        fn_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_sync_module_from_disk")
        ns = {"os": os, "importlib": importlib}
        exec(compile(ast.Module(body=[fn_node], type_ignores=[]), app_path, "exec"), ns)
        sync_fn = ns["_sync_module_from_disk"]

        # 1. Modul baru/segar dengan _MODULE_MTIME cocok -> tidak boleh reload ulang
        with patch("importlib.reload") as mock_reload:
            res = sync_fn(db_history)
            self.assertIs(res, db_history)
            mock_reload.assert_not_called()

        # 2. Modul lama/stale tanpa _MODULE_MTIME -> wajib close pool + reload 1x
        stale = types.ModuleType("_dummy_stale_mod")
        stale.__file__ = db_history.__file__
        closed = {"flag": False}
        stale.close_all_pooled_connections = lambda: closed.__setitem__("flag", True)

        with patch("importlib.reload", return_value=db_history) as mock_reload:
            res2 = sync_fn(stale)
            self.assertTrue(closed["flag"])
            mock_reload.assert_called_once_with(stale)
            self.assertIs(res2, db_history)

    def test_null_ai_values_barcode_sentence_guard_and_bom_backup_restore(self):
        import json
        from unittest.mock import patch
        import nutrition_engine

        # BUG-06: nilai None pada komponen AI & JSON BOM + null fields saat restore
        res_null = nutrition_engine.calculate_dish_nutrition(
            [{
                "name": "Hidangan Test Null",
                "weight_g": None,
                "energy_kcal_per_100g": None,
                "protein_g_per_100g": 5.0,
                "fat_g_per_100g": None,
                "carb_g_per_100g": None,
                "fiber_g_per_100g": None,
                "sodium_mg_per_100g": None,
            }],
            portion_multiplier=None,
            auto_learn=False,
        )
        self.assertEqual(res_null["totals"]["energy_kcal"], 0.0)

        bom_backup = "\ufeff" + json.dumps({
            "meal_logs": [{
                "dish_name": "Soto BOM",
                "energy_kcal": 250.0,
                "protein_g": None,
                "fat_g": None,
                "carb_g": None,
                "fiber_g": None,
                "sodium_mg": None,
                "portion_multiplier": None,
                "photo_caption": None,
                "meal_type": None,
                "logged_at": None,
            }],
            "weight_logs": [{"recorded_date": "2026-11-18", "weight_kg": 66.5, "note": None}],
            "custom_foods": [{"food_name": "Kopi Susu Custom", "serving_size": "1 gelas", "energy_kcal": 140.0, "protein_g": None}],
        })
        ok_imp, msg_imp = db_history.import_user_data_json(self.test_uid, bom_backup)
        self.assertTrue(ok_imp, msg_imp)
        self.assertEqual(len(db_history.get_custom_foods(self.test_uid)), 1)

        # BUG-07: kalimat makanan dengan total >= 8 digit tidak boleh memicu API Open Food Facts
        with patch("nutrition_engine.fetch_open_food_facts") as mock_off:
            nutrition_engine.find_best_match("2 telur 100g + nasi putih 150g + tahu 50g")
            mock_off.assert_not_called()


if __name__ == "__main__":
    unittest.main()

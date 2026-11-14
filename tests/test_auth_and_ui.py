"""
Unit Test untuk Fitur Keamanan Auth, Open Beta 5x Kuota, Zona Waktu WITA, Berat Badan, Streak, & Cache AI.
"""

import sys
import os
import sqlite3
import hashlib
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import gemini_extractor
from db_history import (
    DB_PATH,
    init_user_history_tables, register_user, authenticate_user,
    get_or_create_user, get_user_scan_status, record_scan_usage,
    update_calorie_target, update_user_theme, update_user_preferences,
    is_admin_user, create_session_token, verify_session_token,
    log_weight_entry, get_weight_history, log_meal, get_user_history_stats,
    get_logging_streak, get_local_now
)

import uuid

class TestAuthAndUI(unittest.TestCase):
    def setUp(self):
        init_user_history_tables()
        self.test_uid = f"test_{uuid.uuid4().hex[:10]}@example.com"
        self.test_pin = "123456"

    def tearDown(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
            cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (self.test_uid,))
        conn.commit()
        conn.close()

    def test_registration_and_open_beta_five_scans(self):
        success, res = register_user(
            self.test_uid,
            display_name="Tester Sehat",
            pin_or_pass=self.test_pin,
            gender="Pria",
            bb=70.0,
            tb=175.0,
            age=28,
            target_kcal=2100.0,
            focus_goal="Kendali Natrium (Hipertensi)",
            timezone_offset=8
        )
        self.assertTrue(success, f"Registrasi gagal: {res}")
        self.assertEqual(res["user_id"], self.test_uid)
        self.assertEqual(res["display_name"], "Tester Sehat")
        self.assertTrue(res["password_hash"].startswith("pbkdf2$"))
        self.assertEqual(res["focus_goal"], "Kendali Natrium (Hipertensi)")
        self.assertEqual(int(res["timezone_offset"]), 8)

        # Open Beta: terdaftar mendapat kuota 5x scan foto per hari (3 makan berat + 2 jajan)
        status = get_user_scan_status(self.test_uid, tz_offset=8)
        self.assertTrue(status["is_beta"])
        self.assertEqual(status["max_scans"], 5)
        self.assertTrue(status["can_scan"])

        for _ in range(5):
            record_scan_usage(self.test_uid, tz_offset=8)
        status_after = get_user_scan_status(self.test_uid, tz_offset=8)
        self.assertEqual(status_after["scans_today"], 5)
        self.assertFalse(status_after["can_scan"], "Scan ke-6 harus dibatasi")

        # Berat awal otomatis tercatat di weight_logs
        w_hist = get_weight_history(self.test_uid)
        self.assertEqual(len(w_hist), 1)
        self.assertEqual(w_hist[0]["weight_kg"], 70.0)

    def test_authentication_and_legacy_hash_upgrade(self):
        register_user(self.test_uid, "Tester Auth", self.test_pin)

        # Sukses login dengan PIN benar (PBKDF2)
        auth_ok, user_data = authenticate_user(self.test_uid, self.test_pin)
        self.assertTrue(auth_ok)
        self.assertEqual(user_data["user_id"], self.test_uid)

        # Gagal login dengan PIN salah
        auth_fail, err = authenticate_user(self.test_uid, "999999")
        self.assertFalse(auth_fail)
        self.assertIn("salah", err.lower())

        # Simulasikan user lama ber-hash SHA-256 polos, pastikan login berhasil & auto-upgrade ke PBKDF2
        legacy_sha = hashlib.sha256(self.test_pin.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE users SET password_hash = ? WHERE user_id = ?", (legacy_sha, self.test_uid))
        conn.commit()
        conn.close()

        ok_leg, upgraded_user = authenticate_user(self.test_uid, self.test_pin)
        self.assertTrue(ok_leg)
        self.assertTrue(upgraded_user["password_hash"].startswith("pbkdf2$"))

    def test_admin_exact_match_and_session_tokens(self):
        self.assertTrue(is_admin_user("nabillah"))
        self.assertTrue(is_admin_user("admin"))
        self.assertFalse(is_admin_user("budi_admin"))
        self.assertFalse(is_admin_user("fan_nabillah"))
        self.assertFalse(is_admin_user("dwimey"))

        tok = create_session_token(self.test_uid)
        self.assertTrue(len(tok) >= 16)
        self.assertTrue(verify_session_token(self.test_uid, tok))
        self.assertFalse(verify_session_token(self.test_uid, "token_palsu_123456"))
        self.assertFalse(verify_session_token("Tamu (Demo)", tok))

    def test_bmr_mifflin_st_jeor_formula(self):
        bb, tb, usia = 70.0, 175.0, 25
        bmr_pria = (10 * bb) + (6.25 * tb) - (5 * usia) + 5
        self.assertAlmostEqual(bmr_pria, 1673.75, places=1)

        bb_w, tb_w = 55.0, 160.0
        bmr_wanita = (10 * bb_w) + (6.25 * tb_w) - (5 * usia) - 161
        self.assertAlmostEqual(bmr_wanita, 1264.0, places=1)

    def test_profile_weight_streak_and_sodium(self):
        register_user(self.test_uid, "Tester Update", self.test_pin, bb=72.0)

        update_calorie_target(self.test_uid, 2250.0)
        update_user_theme(self.test_uid, "Cal AI Dark")
        update_user_preferences(self.test_uid, timezone_offset=7, focus_goal="Kendali Gula (Diabetes)")

        u = get_or_create_user(self.test_uid)
        self.assertEqual(float(u["daily_calorie_target"]), 2250.0)
        self.assertEqual(u["theme_preference"], "Cal AI Dark")
        self.assertEqual(int(u["timezone_offset"]), 7)
        self.assertEqual(u["focus_goal"], "Kendali Gula (Diabetes)")

        # Catat berat badan baru & uji streak 2 hari berturut-turut
        today_local = get_local_now(8).date()
        yesterday_str = (today_local - timedelta(days=1)).strftime("%Y-%m-%d")
        today_str = today_local.strftime("%Y-%m-%d")

        log_weight_entry(self.test_uid, 71.2, tz_offset=8, recorded_date=today_str)
        log_meal(self.test_uid, "Sarapan Pagi", {"energy_kcal": 350, "protein_g": 15, "fat_g": 10, "carb_g": 45, "fiber_g": 4, "sodium_mg": 520}, log_date=yesterday_str, tz_offset=8)
        log_meal(self.test_uid, "Makan Siang", {"energy_kcal": 500, "protein_g": 28, "fat_g": 14, "carb_g": 60, "fiber_g": 5, "sodium_mg": 800}, log_date=today_str, tz_offset=8)

        stats = get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats["today_totals"]["sodium_mg"], 800.0)
        self.assertEqual(get_logging_streak(self.test_uid, tz_offset=8), 2)

    def test_gemini_text_cache(self):
        gemini_extractor._TEXT_ANALYSIS_CACHE.clear()
        fake_resp = MagicMock()
        fake_resp.text = '{"dish_name": "Nasi Goreng", "confidence": "high", "portion_category": "sedang", "components": [], "health_tip": "Kurangi minyak."}'
        fake_model = MagicMock()
        fake_model.generate_content.return_value = fake_resp

        with patch.object(gemini_extractor, "get_gemini_client", return_value=("legacy", fake_model)):
            r1 = gemini_extractor.analyze_food_text("  Nasi   Goreng ", api_key="dummy")
            r2 = gemini_extractor.analyze_food_text("nasi goreng", api_key="dummy")

        self.assertEqual(r1["dish_name"], "Nasi Goreng")
        self.assertEqual(r2["dish_name"], "Nasi Goreng")
        self.assertEqual(fake_model.generate_content.call_count, 1)

if __name__ == "__main__":
    unittest.main()

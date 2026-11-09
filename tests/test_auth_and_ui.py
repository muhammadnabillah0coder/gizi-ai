"""
Unit Test untuk Fitur Autentikasi, Kalkulator BMR, dan Status PRO Nutrisi Cerdas.
"""

import sys
import os
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db_history import (
    init_user_history_tables, register_user, authenticate_user,
    get_or_create_user, get_user_scan_status, update_calorie_target,
    update_user_theme
)

import uuid

class TestAuthAndUI(unittest.TestCase):
    def setUp(self):
        init_user_history_tables()
        self.test_uid = f"test_{uuid.uuid4().hex[:10]}@example.com"
        self.test_pin = "123456"

    def test_registration_and_pro_bonus(self):
        # Uji registrasi pengguna baru
        success, res = register_user(
            self.test_uid, 
            display_name="Tester Sehat", 
            pin_or_pass=self.test_pin,
            gender="Pria", 
            bb=70.0, 
            tb=175.0, 
            age=28, 
            target_kcal=2100.0
        )
        self.assertTrue(success, f"Registrasi gagal: {res}")
        self.assertEqual(res["user_id"], self.test_uid)
        self.assertEqual(res["display_name"], "Tester Sehat")

        # Uji bahwa status PRO 30 Hari aktif otomatis
        status = get_user_scan_status(self.test_uid)
        self.assertTrue(status["is_pro"], "Bonus PRO 30 hari harus aktif otomatis")
        self.assertGreaterEqual(status["days_left"], 29, "Sisa hari PRO minimal 29 hari")
        self.assertTrue(status["can_scan"], "User PRO harus dapat melakukan scan")

    def test_authentication(self):
        # Register user
        register_user(self.test_uid, "Tester Auth", self.test_pin)
        
        # Sukses login dengan PIN benar
        auth_ok, user_data = authenticate_user(self.test_uid, self.test_pin)
        self.assertTrue(auth_ok)
        self.assertEqual(user_data["user_id"], self.test_uid)

        # Gagal login dengan PIN salah
        auth_fail, err = authenticate_user(self.test_uid, "999999")
        self.assertFalse(auth_fail)
        self.assertIn("salah", err.lower())

    def test_bmr_mifflin_st_jeor_formula(self):
        # Pria: 10*BB + 6.25*TB - 5*Usia + 5
        # BB 70, TB 175, Usia 25 -> 700 + 1093.75 - 125 + 5 = 1673.75
        bb, tb, usia = 70.0, 175.0, 25
        bmr_pria = (10 * bb) + (6.25 * tb) - (5 * usia) + 5
        self.assertAlmostEqual(bmr_pria, 1673.75, places=1)

        # Wanita: 10*BB + 6.25*TB - 5*Usia - 161
        # BB 55, TB 160, Usia 25 -> 550 + 1000 - 125 - 161 = 1264
        bb_w, tb_w = 55.0, 160.0
        bmr_wanita = (10 * bb_w) + (6.25 * tb_w) - (5 * usia) - 161
        self.assertAlmostEqual(bmr_wanita, 1264.0, places=1)

    def test_profile_updates(self):
        register_user(self.test_uid, "Tester Update", self.test_pin)
        
        # Update target kalori
        update_calorie_target(self.test_uid, 2250.0)
        u = get_or_create_user(self.test_uid)
        self.assertEqual(float(u["daily_calorie_target"]), 2250.0)

        # Update tema
        update_user_theme(self.test_uid, "Cal AI Dark")
        u = get_or_create_user(self.test_uid)
        self.assertEqual(u["theme_preference"], "Cal AI Dark")

if __name__ == "__main__":
    unittest.main()

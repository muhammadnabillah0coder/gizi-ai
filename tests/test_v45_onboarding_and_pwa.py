"""
Suite Pengujian Regresi v4.5.0 Nutrisi Cerdas:
1. Mesin Kuis Onboarding Personal 4 Langkah (build_personalized_nutrition_plan):
   IMT Kemenkes RI, defisit/surplus/maintenance, pengaman klinis Ibu Hamil (+300 kkal),
   batas GGL Diabetes (25g gula) & Hipertensi (1500mg natrium), hidrasi adaptif, estimasi minggu.
2. Kesiapan Publik PWA & Google Cloud Run Jakarta:
   manifest.json valid, ikon PNG 192x192 & 512x512 valid, enableStaticServing = true,
   injeksi manifest di session_cookie.py, serta skrip deploy bebas rahasia hardcoded.
3. Integrasi AppTest E2E Kuis Onboarding 4 Langkah:
   Buka kuis sebagai pengunjung baru -> Langkah 1 -> 2 -> 3 -> 4 -> Terapkan ke sesi tamu
   dan verifikasi profil, target kalori, fokus klinis, serta mode puasa tersimpan tanpa crash.
"""

import json
import os
import sqlite3
import sys
import unittest
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history
import nutrition_engine
import session_cookie


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestV45OnboardingAndPwa(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.created_uids = []

    def tearDown(self):
        if not self.created_uids:
            return
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for uid in self.created_uids:
            for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()

    def test_01_build_personalized_nutrition_plan_math_and_clinical_guards(self):
        # 1. Defisit terukur untuk diet
        plan_diet = nutrition_engine.build_personalized_nutrition_plan(
            gender="Pria",
            weight_kg=80.0,
            height_cm=170.0,
            age_years=30,
            target_weight_kg=72.0,
            activity_level="Ringan (Olahraga 1-3 hari/minggu)",
            goal_choice="Turunkan Berat Badan",
            focus_goal="Diet Sehat",
            fasting_mode="Puasa Sunnah / Ramadan",
        )
        self.assertAlmostEqual(plan_diet["bmi"], 27.7, places=1)
        self.assertIn("Obesitas", plan_diet["bmi_category"])
        self.assertEqual(plan_diet["adjustment_kcal"], -400.0)
        self.assertLess(plan_diet["target_kcal"], plan_diet["tdee"])
        self.assertGreater(plan_diet["estimated_weeks"], 15)
        self.assertGreaterEqual(plan_diet["water_glasses"], 10)
        self.assertEqual(plan_diet["macros"]["sugar_g"], 50.0)

        # 2. Pengaman Ibu Hamil: walaupun pengguna memilih "Turunkan Berat Badan", tidak boleh defisit!
        plan_bumil = nutrition_engine.build_personalized_nutrition_plan(
            gender="Wanita",
            weight_kg=60.0,
            height_cm=160.0,
            age_years=27,
            target_weight_kg=55.0,
            activity_level="Sedentari",
            goal_choice="Turunkan Berat Badan",
            focus_goal="Ibu Hamil & Menyusui",
        )
        self.assertEqual(plan_bumil["adjustment_kcal"], 300.0)
        self.assertGreater(plan_bumil["target_kcal"], plan_bumil["tdee"])
        self.assertIn("Ibu Hamil", plan_bumil["strategy_label"])

        # 3. Diabetes & Hipertensi membatasi gula & natrium secara klinis
        plan_dm = nutrition_engine.build_personalized_nutrition_plan(
            gender="Wanita", weight_kg=62.0, height_cm=158.0, age_years=45,
            goal_choice="Jaga Berat Badan Ideal", focus_goal="Kendali Gula (Diabetes)",
        )
        self.assertEqual(plan_dm["macros"]["sugar_g"], 25.0)

        plan_ht = nutrition_engine.build_personalized_nutrition_plan(
            gender="Pria", weight_kg=70.0, height_cm=168.0, age_years=50,
            goal_choice="Jaga Berat Badan Ideal", focus_goal="Kendali Natrium (Hipertensi)",
        )
        self.assertEqual(plan_ht["macros"]["sodium_mg"], 1500.0)

    def test_02_pwa_manifest_icons_and_cloud_run_assets_valid(self):
        # Manifest & ikon PWA
        manifest_path = os.path.join(ROOT_DIR, "static", "manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        self.assertEqual(manifest.get("display"), "standalone")
        self.assertEqual(manifest.get("theme_color"), "#15803D")
        icon_srcs = {ic["src"] for ic in manifest.get("icons", [])}
        self.assertIn("/app/static/icon-192.png", icon_srcs)
        self.assertIn("/app/static/icon-512.png", icon_srcs)

        for fname, expected_size in (("icon-192.png", (192, 192)), ("icon-512.png", (512, 512))):
            ipath = os.path.join(ROOT_DIR, "static", fname)
            self.assertTrue(os.path.exists(ipath))
            with Image.open(ipath) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.size, expected_size)

        # Static serving aktif di config.toml
        cfg_path = os.path.join(ROOT_DIR, ".streamlit", "config.toml")
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg_txt = fh.read()
        self.assertIn("enableStaticServing = true", cfg_txt)

        # Injeksi <link rel="manifest"> ada di session_cookie.py
        self.assertIn("/app/static/manifest.json", session_cookie._COOKIE_BRIDGE_JS)
        self.assertIn("injectPwaHead", session_cookie._COOKIE_BRIDGE_JS)

        # Skrip Cloud Run & panduan domain ada dan bebas rahasia hardcoded
        for rel_name in ("deploy_cloud_run.ps1", "deploy_cloud_run.sh", "DEPLOY_PUBLIC_GUIDE.md"):
            fpath = os.path.join(ROOT_DIR, rel_name)
            self.assertTrue(os.path.exists(fpath), f"{rel_name} tidak ditemukan")
            with open(fpath, "r", encoding="utf-8") as fh:
                body = fh.read()
            self.assertIn("asia-southeast2", body)
            self.assertNotIn("AIzaSy", body)
            self.assertNotIn("GOCSPX-", body)

    def test_03_apptest_4_step_onboarding_wizard_to_guest_plan_application(self):
        from streamlit.testing.v1 import AppTest

        app_path = os.path.join(ROOT_DIR, "app.py")
        at = AppTest.from_file(app_path, default_timeout=30)
        at.run()
        self.assertEqual(len(at.exception), 0, f"Boot crash: {at.exception}")

        guest_uid = at.session_state["user"]["user_id"]
        self.assertTrue(db_history.is_guest_user_id(guest_uid))
        self.created_uids.append(guest_uid)

        # Klik "Susun rencana personal"
        at.button(key="btn_open_onboard").click().run()
        self.assertEqual(len(at.exception), 0, f"Step 1 crash: {at.exception}")
        self.assertTrue(at.session_state["show_onboarding_wizard"])
        self.assertEqual(at.session_state["onboard_step"], 1)

        # Langkah 1: pilih fokus Diabetes + lanjut
        at.selectbox(key="ob_focus_select").select("Kendali Gula (Diabetes)").run()
        at.button(key="ob_next_1").click().run()
        self.assertEqual(len(at.exception), 0, f"Step 2 crash: {at.exception}")
        self.assertEqual(at.session_state["onboard_step"], 2)

        # Langkah 2: atur berat 78 kg, tinggi 168 cm, target 70 kg + lanjut
        at.number_input(key="ob_weight_num").set_value(78.0).run()
        at.number_input(key="ob_height_num").set_value(168.0).run()
        at.number_input(key="ob_target_w_num").set_value(70.0).run()
        at.button(key="ob_next_2").click().run()
        self.assertEqual(len(at.exception), 0, f"Step 3 crash: {at.exception}")
        self.assertEqual(at.session_state["onboard_step"], 3)

        # Langkah 3: pilih Puasa Sunnah / Ramadan + hitung rencana
        at.radio(key="ob_fast_radio").set_value("Puasa Sunnah / Ramadan").run()
        at.button(key="ob_next_3").click().run()
        self.assertEqual(len(at.exception), 0, f"Step 4 crash: {at.exception}")
        self.assertEqual(at.session_state["onboard_step"], 4)

        all_md_step4 = "\n".join(m.value for m in at.markdown)
        self.assertIn("Target Energi Harian Personal", all_md_step4)
        self.assertIn("25 g", all_md_step4)  # Batas gula Diabetes
        self.assertIn("Puasa Sunnah / Ramadan", all_md_step4)

        # Langkah 4: terapkan ke sesi tamu
        at.button(key="ob_btn_apply_guest").click().run()
        self.assertEqual(len(at.exception), 0, f"Apply guest crash: {at.exception}")
        self.assertFalse(at.session_state["show_onboarding_wizard"])

        updated_u = db_history.get_or_create_user(guest_uid)
        self.assertEqual(updated_u["focus_goal"], "Kendali Gula (Diabetes)")
        self.assertEqual(updated_u["fasting_mode"], "Puasa Sunnah / Ramadan")
        self.assertAlmostEqual(float(updated_u["weight_kg"]), 78.0, places=1)
        self.assertNotEqual(float(updated_u["daily_calorie_target"]), 2000.0)


if __name__ == "__main__":
    unittest.main()

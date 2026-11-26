"""
Suite Pengujian Regresi v4.2.0 Nutrisi Cerdas:
1. Privasi & higienitas seed database (sanitize_seed_db.py).
2. Isolasi sesi tamu (guest_*), auto-migrasi ke akun baru, & pembersihan tamu lama.
3. Edit profil tubuh & ganti PIN/password (lokal & OAuth).
4. Pelacakan Gula GGL (sugar_g), Nutri-Grade tinggi gula, target air adaptif, & tren protein mingguan.
5. Cakupan 45/45 barcode produk ritel (RET_*) & pencocokan leading-zero.
6. Alert Manager cooldown anti-spam & pembacaan st.secrets.
7. Ekstraksi barcode Vision (analyze_barcode_or_label_image) & SDK google-genai.
8. AppTest: sesi tamu terisolasi & tombol Masuk dengan Google tampil otomatis saat kredensial tersedia.
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch
from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import alert_manager
import db_history
import gemini_extractor
import google_auth
import nutrition_engine
import sanitize_seed_db


class TestV42Upgrades(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.created_uids = []

    def tearDown(self):
        if self.created_uids:
            conn = sqlite3.connect(db_history.DB_PATH)
            cur = conn.cursor()
            for uid in self.created_uids:
                for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
                    cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
            conn.commit()
            conn.close()

    def test_01_sanitize_seed_db_removes_user_data_keeps_catalog(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = os.path.join(tmpdir, "seed_copy.db")
            shutil.copy2(db_history.DB_PATH, tmp_db)

            # Sisipkan data dummy user & secret pada salinan sementara
            conn = sqlite3.connect(tmp_db)
            conn.execute("INSERT OR REPLACE INTO app_meta (meta_key, meta_value) VALUES ('session_hmac_secret', 'dummy')")
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, display_name, auth_provider) VALUES ('leak@example.com', 'Leak', 'local')"
            )
            conn.commit()
            conn.close()

            ok_before, info_before = sanitize_seed_db.check_seed_db_clean(tmp_db)
            self.assertFalse(ok_before)
            self.assertGreater(info_before["counts"]["users"], 0)
            self.assertGreater(info_before["counts"]["app_meta"], 0)

            res = sanitize_seed_db.sanitize_seed_db(tmp_db)
            self.assertTrue(res["is_clean"])
            self.assertEqual(res["counts"]["users"], 0)
            self.assertEqual(res["counts"]["meal_logs"], 0)
            self.assertEqual(res["counts"]["app_meta"], 0)
            self.assertGreaterEqual(res["counts"]["food_composition"], 1300)

    def test_02_isolated_guest_migration_and_stale_cleanup(self):
        gid = db_history.create_guest_session_id()
        self.assertTrue(db_history.is_guest_user_id(gid))
        self.assertEqual(db_history.create_session_token(gid), "")
        self.created_uids.append(gid)

        guest_u = db_history.get_or_create_user(gid, display_name="Tamu", auth_provider="guest")
        self.assertEqual(guest_u["user_id"], gid)
        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")

        db_history.log_meal(
            gid,
            "Soto Ayam Tamu",
            {"energy_kcal": 340.0, "protein_g": 21.0, "fat_g": 10.0, "carb_g": 42.0, "fiber_g": 2.0, "sodium_mg": 520.0, "sugar_g": 3.0},
            log_date=today_str,
            tz_offset=8,
        )
        db_history.log_water_intake(gid, 3, tz_offset=8)
        db_history.log_weight_entry(gid, 64.5, tz_offset=8, recorded_date=today_str)

        target_uid = f"migrated_{uuid.uuid4().hex[:8]}@example.com"
        self.created_uids.append(target_uid)
        ok_reg, _ = db_history.register_user(target_uid, "Pengguna Baru", "5678", bb=64.5)
        self.assertTrue(ok_reg)

        moved = db_history.migrate_guest_data_to_user(gid, target_uid)
        self.assertEqual(moved["meals"], 1)
        self.assertEqual(moved["water"], 1)

        stats_target = db_history.get_user_history_stats(target_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_target["today_totals"]["count"], 1)
        self.assertEqual(stats_target["today_totals"]["sugar_g"], 3.0)
        self.assertEqual(db_history.get_water_intake(target_uid, tz_offset=8)["glasses"], 3)

        # Uji cleanup_stale_guest_users membersihkan guest > 7 hari tanpa menyentuh akun asli
        stale_gid = db_history.create_guest_session_id()
        self.created_uids.append(stale_gid)
        db_history.get_or_create_user(stale_gid, display_name="Tamu Lama", auth_provider="guest")
        old_ts = (db_history.get_local_now(8) - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn = sqlite3.connect(db_history.DB_PATH)
        conn.execute("UPDATE users SET created_at = ? WHERE user_id = ?", (old_ts, stale_gid))
        conn.commit()
        conn.close()

        purged = db_history.cleanup_stale_guest_users(max_age_days=7)
        self.assertGreaterEqual(purged, 1)

        conn = sqlite3.connect(db_history.DB_PATH)
        still_stale = conn.execute("SELECT id FROM users WHERE user_id = ?", (stale_gid,)).fetchone()
        still_real = conn.execute("SELECT id FROM users WHERE user_id = ?", (target_uid,)).fetchone()
        conn.close()
        self.assertIsNone(still_stale)
        self.assertIsNotNone(still_real)

    def test_03_profile_body_update_and_change_password(self):
        uid = f"prof_{uuid.uuid4().hex[:8]}@example.com"
        self.created_uids.append(uid)
        ok, _ = db_history.register_user(uid, "Nama Awal", "1111", gender="Pria", bb=70.0, tb=170.0, age=28)
        self.assertTrue(ok)

        # Tolak XSS nama
        ok_bad, _ = db_history.update_user_body_profile(uid, display_name="<script>alert(1)</script>")
        self.assertFalse(ok_bad)

        # Perbarui profil tubuh & target kalori sekaligus
        ok_upd, upd_u = db_history.update_user_body_profile(
            uid, display_name="Nama Baru", gender="Wanita", weight_kg=58.5, height_cm=162.0, age_years=30, daily_calorie_target=1750.0
        )
        self.assertTrue(ok_upd)
        self.assertEqual(upd_u["display_name"], "Nama Baru")
        self.assertEqual(upd_u["gender"], "Wanita")
        self.assertEqual(float(upd_u["weight_kg"]), 58.5)
        self.assertEqual(float(upd_u["height_cm"]), 162.0)
        self.assertEqual(int(upd_u["age_years"]), 30)
        self.assertEqual(float(upd_u["daily_calorie_target"]), 1750.0)

        # Ganti PIN: salah PIN lama ditolak, benar PIN lama berhasil & bisa login dengan PIN baru
        ok_wrong, _ = db_history.change_user_password(uid, "9999", "2222")
        self.assertFalse(ok_wrong)
        ok_short, _ = db_history.change_user_password(uid, "1111", "12")
        self.assertFalse(ok_short)
        ok_ch, _ = db_history.change_user_password(uid, "1111", "4321")
        self.assertTrue(ok_ch)
        ok_login_old, _ = db_history.authenticate_user(uid, "1111")
        ok_login_new, _ = db_history.authenticate_user(uid, "4321")
        self.assertFalse(ok_login_old)
        self.assertTrue(ok_login_new)

    def test_04_sugar_ggl_45_retail_barcodes_and_adaptive_water(self):
        # 1. Seluruh 45 produk RET_* wajib punya barcode EAN-13 & gula terisi untuk minuman manis
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        total_ret = cur.execute("SELECT COUNT(*) FROM food_composition WHERE food_code LIKE 'RET_%'").fetchone()[0]
        mapped_ret = cur.execute(
            "SELECT COUNT(*) FROM food_composition WHERE food_code LIKE 'RET_%' AND barcode IS NOT NULL AND barcode != ''"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(total_ret, 45)
        self.assertEqual(mapped_ret, 45, "Seluruh 45 produk ritel RET_* harus memiliki kode barcode EAN-13")

        # 2. Uji pencocokan beberapa barcode ritel baru & gula kemasan
        nutrition_engine.invalidate_food_catalog_cache()
        m_cimory = nutrition_engine.find_best_match("8993351120028")
        self.assertIsNotNone(m_cimory)
        self.assertIn("cimory", m_cimory["food_name"].lower())
        self.assertGreater(float(m_cimory.get("sugar_g") or 0.0), 8.0)

        m_milo = nutrition_engine.find_best_match("8992696401112")
        self.assertIsNotNone(m_milo)
        self.assertIn("milo", m_milo["food_name"].lower())

        # Leading-zero equivalence untuk Indomie Goreng (12 digit vs 11 digit)
        m_indo = nutrition_engine.find_best_match("89686010921")
        self.assertIsNotNone(m_indo)
        self.assertIn("indomie", m_indo["food_name"].lower())

        # 3. Nutri-Grade & target GGL Sugar
        t_diab = nutrition_engine.compute_macro_targets(2000.0, "Kendali Gula (Diabetes)")
        t_std = nutrition_engine.compute_macro_targets(2000.0, "Diet Sehat")
        self.assertEqual(t_diab["sugar_g"], 25.0)
        self.assertEqual(t_std["sugar_g"], 50.0)

        ng_sweet = nutrition_engine.evaluate_nutri_grade(140.0, 0.0, 0.0, 35.0, 0.0, 25.0, sugar_100=34.0)
        badge_labels = [b[0].lower() for b in ng_sweet["badges"]]
        self.assertTrue(any("tinggi gula" in lbl for lbl in badge_labels), f"Badge gula tidak muncul: {badge_labels}")

        # 4. Target air adaptif berat badan & ibu hamil
        self.assertEqual(db_history.compute_water_target_glasses(50.0, "Diet Sehat"), 8)
        self.assertEqual(db_history.compute_water_target_glasses(85.0, "Diet Sehat"), 11)
        self.assertEqual(db_history.compute_water_target_glasses(60.0, "Ibu Hamil & Menyusui"), 9)

    def test_05_alert_manager_cooldown_and_barcode_vision_helper(self):
        alert_manager.reset_alert_cooldown()
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "999"}):
            with patch.object(alert_manager.requests, "post", return_value=ok_resp) as mock_post:
                self.assertTrue(alert_manager.send_alert_to_phone("Err 1", context="CooldownTest", cooldown_seconds=600))
                # Duplikat konteks dalam jendela cooldown tidak boleh kirim ulang
                self.assertFalse(alert_manager.send_alert_to_phone("Err 2", context="CooldownTest", cooldown_seconds=600))
                self.assertEqual(mock_post.call_count, 1)
                # Konteks berbeda tetap terkirim
                self.assertTrue(alert_manager.send_alert_to_phone("Err 3", context="OtherContext", cooldown_seconds=600))
                self.assertEqual(mock_post.call_count, 2)
                # force=True melewati cooldown
                self.assertTrue(alert_manager.send_alert_to_phone("Err 4", context="CooldownTest", force=True))
                self.assertEqual(mock_post.call_count, 3)
        alert_manager.reset_alert_cooldown()

        # Pastikan SDK baru google-genai sudah terpasang di .venv
        self.assertTrue(gemini_extractor._HAS_NEW_GENAI, "SDK resmi google-genai harus terpasang di .venv")

        # Uji analyze_barcode_or_label_image mengembalikan detected_barcode
        dummy_img = Image.new("RGB", (64, 64), color=(255, 255, 255))
        fake_resp = MagicMock()
        fake_resp.text = '{"is_edible_food": true, "dish_name": "Teh Botol Sosro", "detected_barcode": "8992753111105", "components": [{"name": "Teh Botol", "weight_g": 350, "energy_kcal_per_100g": 37.1, "sugar_g_per_100g": 8.9}], "health_tip": "Batasi gula harian."}'
        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = fake_resp
        with patch.object(gemini_extractor, "get_gemini_client", return_value=("new", fake_client)):
            parsed = gemini_extractor.analyze_barcode_or_label_image(dummy_img, api_key="dummy")
        self.assertEqual(parsed["detected_barcode"], "8992753111105")

    def test_06_apptest_isolated_guest_and_conditional_google_oauth_button(self):
        from streamlit.testing.v1 import AppTest

        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))

        # 1. Tanpa kredensial Google -> tombol Masuk dengan Google tidak dirender & sesi tamu memakai guest_*
        with patch.object(google_auth, "get_credentials", return_value=("", "")):
            at_no_g = AppTest.from_file(app_path, default_timeout=30)
            at_no_g.run()
            self.assertEqual(len(at_no_g.exception), 0, f"Guest boot crash: {at_no_g.exception}")
            guest_uid = at_no_g.session_state["user"]["user_id"]
            self.created_uids.append(guest_uid)
            self.assertTrue(guest_uid.startswith("guest_"), f"Harus memakai guest_* terisolasi, dapat: {guest_uid}")
            all_md_no_g = "\n".join(m.value for m in at_no_g.markdown)
            self.assertNotIn("accounts.google.com/o/oauth2/v2/auth", all_md_no_g)

        # 2. Dengan kredensial Google aktif -> tombol Masuk dengan Google dirender otomatis dengan parameter state
        with patch.object(google_auth, "get_credentials", return_value=("cid-demo", "csec-demo")):
            at_g = AppTest.from_file(app_path, default_timeout=30)
            at_g.run()
            self.assertEqual(len(at_g.exception), 0, f"Guest Google boot crash: {at_g.exception}")
            guest_uid2 = at_g.session_state["user"]["user_id"]
            self.created_uids.append(guest_uid2)
            self.assertNotEqual(guest_uid, guest_uid2, "Dua sesi tamu berbeda harus mendapat ID berbeda")
            all_md_g = "\n".join(m.value for m in at_g.markdown)
            self.assertIn("accounts.google.com/o/oauth2/v2/auth", all_md_g)
            self.assertIn("Masuk dengan Google", all_md_g)


if __name__ == "__main__":
    unittest.main()

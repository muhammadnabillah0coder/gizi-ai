"""
Regresi Keamanan Bug Hunter Pass 2 (Nutrisi Cerdas v4.1.1):
Menguji keenam temuan BH-SEC-01 s/d BH-SEC-06 + TTL token sesi 30 hari:
1. BH-SEC-01: Label kemasan scanner menghormati batas kuota can_scan & mencatat record_scan_usage.
2. BH-SEC-02: Validasi import_user_data_json (anti-negatif/taboo/formula/bad-date), clamp progress bar, & sanitasi CSV.
3. BH-SEC-03: Google OAuth anti-CSRF state parameter (single-use + penolakan ?code= tanpa state sah di AppTest).
4. BH-SEC-04: Redaksi TELEGRAM_BOT_TOKEN pada exception log & HTML escaping di alert_manager.
5. BH-SEC-05: Batas 12.000 kkal & 25 menu/hari pada update_meal_log, scale_meal_log_portion, copy_meals_from_date.
6. BH-SEC-06: Batas piksel gambar aman 25MP (open_safe_image) & token sesi URL HMAC TTL 30 hari (kedaluwarsa & tolak token statis lama).
"""

import ast
import contextlib
import io
import json
import os
import sqlite3
import sys
import time
import unittest
import uuid
from unittest.mock import MagicMock, patch

from PIL import Image

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import alert_manager
import db_history
import food_guardrails as fg
import google_auth


class TestSecurityHardeningV411(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.test_uid = f"sec_{uuid.uuid4().hex[:8]}@example.com"
        ok, _ = db_history.register_user(self.test_uid, "Sec Tester", "1234", bb=65.0)
        self.assertTrue(ok)
        self.other_uids = []

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for uid in [self.test_uid, *self.other_uids]:
            for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "users"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()

    def test_bh_sec_01_packaged_label_scanner_enforces_quota_via_shared_helper(self):
        app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        with open(app_path, "r", encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)

        # Pastikan _execute_vision_scan_and_open_preview memeriksa can_scan & memanggil record_scan_usage
        fn_exec = next(
            n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_execute_vision_scan_and_open_preview"
        )
        exec_src = ast.get_source_segment(src, fn_exec)
        self.assertIn("can_scan", exec_src)
        self.assertIn("record_scan_usage", exec_src)

        # Pastikan subtab_barcode / btn_scan_pkg memanggil helper terpadu & menutup akses saat kuota habis
        idx_pkg = src.index('key="btn_scan_pkg"')
        pkg_window = src[max(0, idx_pkg - 500): idx_pkg + 600]
        self.assertIn("scan_status[\"can_scan\"]", pkg_window)
        self.assertIn("_execute_vision_scan_and_open_preview", pkg_window)

    def test_bh_sec_02_json_restore_guardrails_progress_clamp_and_csv_escaping(self):
        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")

        # 1. Payload seluruhnya tidak valid (kalori negatif, hewan ekstrem, formula, tanggal rusak) -> ditolak
        bad_json = json.dumps({
            "meal_logs": [
                {"dish_name": "=cmd|'/C calc'!A0 katak goreng", "energy_kcal": -500, "logged_at": f"{today_str} 12:00:00"},
                {"dish_name": "Nasi Goreng Biasa", "energy_kcal": 400, "logged_at": "bukan-tanggal"},
                {"dish_name": "Kalori Palsu Nol Makro", "energy_kcal": 600, "protein_g": 0, "fat_g": 0, "carb_g": 0, "logged_at": today_str},
            ],
            "weight_logs": [{"recorded_date": today_str, "weight_kg": 5.0}],
            "custom_foods": [{"food_name": "sandal jepit rebus", "energy_kcal": 120.0}],
        })
        ok_bad, msg_bad = db_history.import_user_data_json(self.test_uid, bad_json)
        self.assertFalse(ok_bad, msg_bad)
        stats_after = db_history.get_user_history_stats(self.test_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_after["today_totals"]["count"], 0)

        # 2. Sanitasi sel CSV mencegah formula injection (=, +, -, @, tab, CR)
        self.assertEqual(fg.sanitize_csv_cell("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(fg.sanitize_csv_cell("+cmd|'calc'!A0"), "'+cmd|'calc'!A0")
        self.assertEqual(fg.sanitize_csv_cell("-2+3"), "'-2+3")
        self.assertEqual(fg.sanitize_csv_cell("@SUM(1,2)"), "'@SUM(1,2)")
        self.assertEqual(fg.sanitize_csv_cell("Nasi Putih"), "Nasi Putih")
        self.assertEqual(fg.sanitize_csv_cell(350.0), 350.0)

        # 3. Legacy negative row di DB langsung tidak boleh menyebabkan dashboard crash
        conn = sqlite3.connect(db_history.DB_PATH)
        conn.execute(
            "INSERT INTO meal_logs (user_id, dish_name, energy_kcal, protein_g, fat_g, carb_g, fiber_g, meal_type, logged_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.test_uid, "Legacy Glitch", -500.0, 0.0, 0.0, 0.0, 0.0, "Sarapan", f"{today_str} 08:00:00"),
        )
        conn.commit()
        conn.close()

        from streamlit.testing.v1 import AppTest
        tok = db_history.create_session_token(self.test_uid)
        at = AppTest.from_file(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py")), default_timeout=30)
        at.query_params["u"] = self.test_uid
        at.query_params["s"] = tok
        at.run()
        self.assertEqual(len(at.exception), 0, f"Progress bar negatif masih crash: {at.exception}")

    def test_bh_sec_03_oauth_state_csrf_generation_replay_and_app_rejection(self):
        with patch.object(google_auth, "get_credentials", return_value=("cid-test", "csec-test")):
            auth_url = google_auth.get_google_auth_url("https://nutrisi-cerdas.streamlit.app")
        self.assertIn("state=", auth_url)
        state_val = dict(p.split("=", 1) for p in auth_url.split("?", 1)[1].split("&"))["state"]

        # Valid sekali pakai, lalu replay kedua ditolak
        self.assertTrue(google_auth.verify_oauth_state(state_val))
        self.assertFalse(google_auth.verify_oauth_state(state_val))
        self.assertFalse(google_auth.verify_oauth_state("state_palsu"))
        expired_state = google_auth.create_oauth_state(ttl_seconds=-10)
        self.assertFalse(google_auth.verify_oauth_state(expired_state))

        # AppTest ?code=... tanpa state sah tidak boleh memanggil exchange_code_for_user
        from streamlit.testing.v1 import AppTest
        with patch("google_auth.exchange_code_for_user") as mock_exch:
            at = AppTest.from_file(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py")), default_timeout=30)
            at.query_params["code"] = "attacker_auth_code"
            at.run()
            mock_exch.assert_not_called()
            self.assertEqual(len(at.exception), 0)
            self.assertTrue(any("state" in e.value.lower() for e in at.error))

    def test_bh_sec_04_telegram_alert_redacts_token_and_uses_html(self):
        secret_tok = "987654:SECRET_UNIT_TOKEN_ABC"
        captured = io.StringIO()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": secret_tok, "TELEGRAM_CHAT_ID": "555"}):
            with patch.object(
                alert_manager.requests,
                "post",
                side_effect=alert_manager.requests.exceptions.ConnectionError(
                    f"HTTPSConnectionPool: Max retries with url: /bot{secret_tok}/sendMessage"
                ),
            ) as mock_post:
                with contextlib.redirect_stdout(captured):
                    ok = alert_manager.send_alert_to_phone("error `backtick` <tag>", context="Audit<Test>")
            self.assertFalse(ok)
            out_txt = captured.getvalue()
            self.assertNotIn(secret_tok, out_txt)
            self.assertIn("[REDACTED]", out_txt)

            sent_payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(sent_payload["parse_mode"], "HTML")
            self.assertIn("&lt;tag&gt;", sent_payload["text"])
            self.assertIn("&lt;Test&gt;", sent_payload["text"])

    def test_bh_sec_05_daily_caps_enforced_across_update_scale_and_copy(self):
        today_str = db_history.get_local_now(8).strftime("%Y-%m-%d")
        meals = []
        for idx in range(4):
            meals.append(
                db_history.log_meal(
                    self.test_uid,
                    f"Paket Besar {idx}",
                    {"energy_kcal": 2500.0, "protein_g": 120.0, "fat_g": 120.0, "carb_g": 235.0, "fiber_g": 8.0},
                    log_date=today_str,
                    tz_offset=8,
                )
            )
        # scale_meal_log_portion 2.0x pada 2500 -> 5000 kkal (lolos batas satuan 5250, namun 12,500 > 12,000 harian -> daily_cap_exceeded)
        with self.assertRaises(fg.FoodGuardrailRejected) as ctx1:
            db_history.scale_meal_log_portion(meals[-1]["id"], self.test_uid, new_multiplier=2.0)
        self.assertEqual(ctx1.exception.rejection_type, "daily_cap_exceeded")

        # update_meal_log menaikkan 1 meal jadi melebihi 12,000 kkal harian -> wajib ditolak
        with self.assertRaises(fg.FoodGuardrailRejected) as ctx2:
            db_history.update_meal_log(
                meals[-1]["id"],
                self.test_uid,
                totals={"energy_kcal": 5000.0, "protein_g": 90.0, "fat_g": 80.0, "carb_g": 500.0, "fiber_g": 10.0},
            )
        self.assertEqual(ctx2.exception.rejection_type, "daily_cap_exceeded")

        # copy_meals_from_date tidak boleh melampaui 25 menu/hari
        copy_uid = f"copycap_{uuid.uuid4().hex[:6]}@example.com"
        self.other_uids.append(copy_uid)
        db_history.register_user(copy_uid, "Copy Cap", "1234")
        yest_str = "2026-11-17"
        for i in range(25):
            db_history.log_meal(
                copy_uid, f"Menu Kemarin {i}",
                {"energy_kcal": 100.0, "protein_g": 3.0, "fat_g": 2.0, "carb_g": 17.0, "fiber_g": 1.0},
                log_date=yest_str, tz_offset=8,
            )
        for i in range(5):
            db_history.log_meal(
                copy_uid, f"Menu Hari Ini {i}",
                {"energy_kcal": 100.0, "protein_g": 3.0, "fat_g": 2.0, "carb_g": 17.0, "fiber_g": 1.0},
                log_date=today_str, tz_offset=8,
            )
        copied_cnt = db_history.copy_meals_from_date(copy_uid, yest_str, today_str, tz_offset=8)
        self.assertLessEqual(copied_cnt, 20)
        stats_copy = db_history.get_user_history_stats(copy_uid, target_date=today_str, tz_offset=8)
        self.assertEqual(stats_copy["today_totals"]["count"], 25)

    def test_bh_sec_06_safe_image_pixel_cap_and_30_day_session_token_ttl(self):
        # 1. Batas piksel aman <= 25MP menolak gambar raksasa (>25MP)
        big_mock = MagicMock()
        big_mock.size = (6000, 6000)  # 36 MP
        with patch("PIL.Image.open", return_value=big_mock):
            with self.assertRaises(fg.FoodGuardrailRejected):
                fg.open_safe_image(io.BytesIO(b"fake"))
        self.assertEqual(Image.MAX_IMAGE_PIXELS, fg.MAX_SAFE_IMAGE_PIXELS)

        # 2. Token sesi 30 hari valid saat aktif, tolak token statis lama tanpa TTL, dan kedaluwarsa > 30 hari
        self.assertEqual(db_history.SESSION_TOKEN_TTL_SECONDS, 30 * 86400)
        tok = db_history.create_session_token(self.test_uid)
        self.assertIn(".", tok)
        self.assertTrue(db_history.verify_session_token(self.test_uid, tok))
        self.assertFalse(db_history.verify_session_token(self.test_uid, "deadbeef1234567890abcdef"))
        self.assertFalse(db_history.session_token_needs_refresh(tok))

        # Simulasikan 20 hari berlalu -> masih valid, namun masuk jendela refresh (<15 hari tersisa)
        with patch.object(db_history.time, "time", return_value=time.time() + (20 * 86400)):
            self.assertTrue(db_history.verify_session_token(self.test_uid, tok))
            self.assertTrue(db_history.session_token_needs_refresh(tok))

        # Simulasikan 30 hari + 10 detik berlalu -> kedaluwarsa & ditolak
        with patch.object(db_history.time, "time", return_value=time.time() + (30 * 86400) + 10):
            self.assertFalse(db_history.verify_session_token(self.test_uid, tok))


if __name__ == "__main__":
    unittest.main()

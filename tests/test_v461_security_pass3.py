"""
Suite Uji Keamanan Pass 3 (Nutrisi Cerdas v4.6.1):
Memverifikasi penambalan penuh seluruh 10 temuan Audit Bug Hunter Pass 3:
1. CRITICAL-01: Blokir registrasi publik ID Admin/sistem & dukungan whitelist ADMIN_EMAILS.
2. HIGH-01: Revokasi token sesi via session_version saat logout/ganti PIN, tolak token legacy 2-bagian,
   isolasi SESSION_SECRET dari GEMINI_API_KEY, & sesi Admin tidak disimpan ke cookie/localStorage 30 hari.
3. HIGH-02: Penukaran voucher relasional tanpa truncation [:500] & pembaruan atomik anti-TOCTOU order/voucher.
4. HIGH-03: Klaim Google OAuth terverifikasi membersihkan PIN penyerang pra-daftar & merevokasi sesinya.
5. HIGH-04: Kuota Tanya Gizi AI & retry foto buram tersimpan persisten di DB (tahan refresh/tab baru).
6. MEDIUM-01: OAuth state terikat browser_binding + replay nonce disimpan persisten di DB (oauth_used_nonces).
7. MEDIUM-02: Midtrans menolak capture+challenge, Mayar fail-closed tanpa amount/status gagal, & bot tolak token URL.
8. MEDIUM-03: Pesan error login seragam & lockout sementara setelah 5x PIN salah.
9. LOW-01 & LOW-02: Guard Markdown di nama pangan, validasi https:// pada link bayar, .dockerignore secrets,
   & notifikasi Telegram send_alert_to_phone aktif di payment_gateway.
"""

import hashlib
import os
import sqlite3
import sys
import unittest
import uuid
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_history
import food_guardrails as fg
import google_auth
import payment_gateway
import session_cookie

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TestSecurityPass3V461(unittest.TestCase):
    def setUp(self):
        db_history.init_user_history_tables()
        self.created_uids = []
        self.created_vouchers = []
        self.test_uid = f"p3_{uuid.uuid4().hex[:8]}@example.com"
        self.created_uids.append(self.test_uid)
        ok, _ = db_history.register_user(self.test_uid, "Pass3 Tester", "1234", bb=65.0)
        self.assertTrue(ok)

    def tearDown(self):
        conn = sqlite3.connect(db_history.DB_PATH)
        cur = conn.cursor()
        for code in self.created_vouchers:
            v_row = cur.execute("SELECT id FROM pro_vouchers WHERE code = ?", (code,)).fetchone()
            if v_row:
                cur.execute("DELETE FROM voucher_redemptions WHERE voucher_id = ?", (v_row[0],))
            cur.execute("DELETE FROM pro_vouchers WHERE code = ?", (code,))
        for uid in self.created_uids:
            for tbl in ("meal_logs", "water_logs", "weight_logs", "custom_foods", "payment_orders", "voucher_redemptions", "users"):
                cur.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (uid,))
        conn.commit()
        conn.close()
        with db_history._VOUCHER_FAIL_LOCK:
            db_history._VOUCHER_FAIL_BUCKETS.clear()

    def test_01_critical01_blocks_admin_public_registration_and_env_override(self):
        for reserved in ("admin", "nabillah", "pkm tanah grogot", "muhammadnabillah0coder@gmail.com", "root"):
            ok, msg = db_history.register_user(reserved, "Penyusup", "9999")
            self.assertFalse(ok, f"ID tercadang {reserved} tidak boleh bisa didaftarkan publik")
            self.assertIn("dicadangkan", msg.lower())

        # Override ADMIN_EMAILS harus membatasi admin hanya ke email terkonfigurasi
        with patch.dict(os.environ, {"ADMIN_EMAILS": "founder@nutrisicerdas.id"}, clear=False):
            self.assertTrue(db_history.is_admin_user("founder@nutrisicerdas.id"))
            self.assertFalse(db_history.is_admin_user("admin"))
            self.assertFalse(db_history.is_admin_user("nabillah"))

    def test_02_high01_session_revocation_secret_isolation_and_admin_ephemeral(self):
        tok1 = db_history.create_session_token(self.test_uid)
        self.assertEqual(len(tok1.split(".")), 3)
        self.assertTrue(db_history.verify_session_token(self.test_uid, tok1))

        # Token format lama 2 bagian tanpa session_version wajib ditolak
        self.assertFalse(db_history.verify_session_token(self.test_uid, f"1999999999.{tok1.split('.')[-1]}"))

        # Ganti PIN harus merevokasi token lama seketika
        ok_ch, _ = db_history.change_user_password(self.test_uid, "1234", "5678")
        self.assertTrue(ok_ch)
        self.assertFalse(db_history.verify_session_token(self.test_uid, tok1))

        tok2 = db_history.create_session_token(self.test_uid)
        self.assertTrue(db_history.verify_session_token(self.test_uid, tok2))

        # Logout (bump_user_session_version) juga langsung membatalkan token aktif
        db_history.bump_user_session_version(self.test_uid)
        self.assertFalse(db_history.verify_session_token(self.test_uid, tok2))

        # Isolasi secret: perubahan GEMINI_API_KEY tidak boleh memengaruhi _get_session_secret_key()
        with patch.dict(os.environ, {"SESSION_SECRET": "", "GEMINI_API_KEY": "AIzaKeySatu"}, clear=False):
            k1 = db_history._get_session_secret_key()
        with patch.dict(os.environ, {"SESSION_SECRET": "", "GEMINI_API_KEY": "AIzaKeyDuaBerbeda"}, clear=False):
            k2 = db_history._get_session_secret_key()
        self.assertEqual(k1, k2)
        expected_gemini_derived = hashlib.sha256(b"nutrisi_cerdas_hmac::AIzaKeySatu").digest()
        self.assertNotEqual(k1, expected_gemini_derived)

        # Admin tidak boleh ditulis ke cookie/localStorage 30 hari
        adm_payload = session_cookie.build_cookie_bridge_payload(
            is_guest=False, is_admin=True, user_id="admin", session_token="x.1.y"
        )
        self.assertEqual(adm_payload, {"action": "admin_ephemeral"})

        # Akun Google tanpa PIN lokal tidak boleh ditanam PIN tanpa autentikasi
        g_email = f"guser_{uuid.uuid4().hex[:6]}@gmail.com"
        self.created_uids.append(g_email)
        db_history.claim_verified_google_account(g_email, "Google User")
        ok_gpin, _ = db_history.change_user_password(g_email, "", "4321")
        self.assertFalse(ok_gpin)

    def test_03_high02_voucher_no_truncation_bypass_and_atomic_payment(self):
        v = db_history.create_pro_voucher(days=14, plan_code="PRO_7D", max_uses=50, note="Anti Truncation")
        self.created_vouchers.append(v["code"])

        # 20 email panjang (~40 char x 20 = 800+ char > batas lama [:500])
        long_uids = []
        for idx in range(20):
            uid = f"pengguna_sangat_panjang_{idx:02d}_{uuid.uuid4().hex[:6]}@example.com"
            long_uids.append(uid)
            self.created_uids.append(uid)
            ok_r, _ = db_history.register_user(uid, f"User {idx}", "1234")
            self.assertTrue(ok_r)
            ok_v, _ = db_history.redeem_pro_voucher(uid, v["code"])
            self.assertTrue(ok_v, f"Redeem ke-{idx} gagal")

        # User ke-20 mencoba redeem ulang -> tetap wajib ditolak (relasional voucher_redemptions)
        ok_dup, msg_dup = db_history.redeem_pro_voucher(long_uids[-1], v["code"])
        self.assertFalse(ok_dup)
        self.assertIn("sudah pernah", msg_dup.lower())

        # Atomic mark_payment_order_paid: jika status sudah paid, panggilan paralel tidak menambah hari Pro lagi
        ord_p = db_history.create_payment_order(self.test_uid, "PRO_30D", 19000, 30, provider="midtrans_snap")
        ok_m1, res_m1 = db_history.mark_payment_order_paid(ord_p["order_id"], external_ref="tx1", expected_amount=19000)
        self.assertTrue(ok_m1)
        exp_after_1 = db_history.get_user_scan_status(self.test_uid)["pro_until"]
        ok_m2, _ = db_history.mark_payment_order_paid(ord_p["order_id"], external_ref="tx2", expected_amount=19000)
        self.assertTrue(ok_m2)
        self.assertEqual(db_history.get_user_scan_status(self.test_uid)["pro_until"], exp_after_1)
        self.assertEqual(res_m1["status"], "paid")

    def test_04_high03_google_oauth_claim_invalidates_pre_registered_attacker(self):
        victim_email = f"korban_{uuid.uuid4().hex[:8]}@gmail.com"
        self.created_uids.append(victim_email)
        ok_att, _ = db_history.register_user(victim_email, "Penyerang", "7777")
        self.assertTrue(ok_att)
        att_tok = db_history.create_session_token(victim_email)
        self.assertTrue(db_history.verify_session_token(victim_email, att_tok))

        # Korban login dengan Google terverifikasi -> klaim membersihkan password_hash & mencabut token penyerang
        claimed = db_history.claim_verified_google_account(victim_email, "Korban Asli")
        self.assertIsNone(claimed["password_hash"])
        self.assertEqual(claimed["auth_provider"], "google")
        self.assertFalse(db_history.verify_session_token(victim_email, att_tok))
        ok_att_login, _ = db_history.authenticate_user(victim_email, "7777")
        self.assertFalse(ok_att_login)

    def test_05_high04_db_backed_coach_and_unclear_quotas_survive_refresh(self):
        for i in range(10):
            ok_q, st_q = db_history.consume_coach_quota(self.test_uid, tz_offset=8)
            self.assertTrue(ok_q, f"Pertanyaan ke-{i+1} harus diizinkan")
            self.assertEqual(st_q["remaining"], 9 - i)

        # Simulasikan F5 / tab baru: baca langsung status dari DB
        fresh_st = db_history.get_coach_quota_status(self.test_uid, tz_offset=8)
        self.assertFalse(fresh_st["can_ask"])
        self.assertEqual(fresh_st["remaining"], 0)
        ok_11, _ = db_history.consume_coach_quota(self.test_uid, tz_offset=8)
        self.assertFalse(ok_11)

        # Aktifkan Pro -> Tanya Gizi AI langsung unlimited
        db_history.activate_pro_tier(self.test_uid, days=30)
        pro_st = db_history.get_coach_quota_status(self.test_uid, tz_offset=8)
        self.assertTrue(pro_st["is_unlimited"])
        self.assertTrue(pro_st["can_ask"])

        # Uji persistensi DB retry foto buram (2x gratis, ke-3 memotong scan)
        r1 = db_history.consume_unclear_retry_or_scan_quota(self.test_uid, tz_offset=8, max_free_retries=2)
        r2 = db_history.consume_unclear_retry_or_scan_quota(self.test_uid, tz_offset=8, max_free_retries=2)
        r3 = db_history.consume_unclear_retry_or_scan_quota(self.test_uid, tz_offset=8, max_free_retries=2)
        self.assertFalse(r1["scan_consumed"])
        self.assertFalse(r2["scan_consumed"])
        self.assertTrue(r3["scan_consumed"])
        self.assertEqual(db_history.get_user_scan_status(self.test_uid, tz_offset=8)["scans_today"], 1)

    def test_06_medium01_oauth_state_browser_binding_and_db_replay_block(self):
        st_a = google_auth.create_oauth_state(browser_binding="browser-nonce-aaa")
        # Browser lain atau binding kosong ditolak saat require_binding=True
        self.assertFalse(google_auth.verify_oauth_state(st_a, browser_binding="browser-nonce-bbb", require_binding=True))
        self.assertFalse(google_auth.verify_oauth_state(st_a, browser_binding="", require_binding=True))

        # Browser cocok berhasil sekali
        self.assertTrue(google_auth.verify_oauth_state(st_a, browser_binding="browser-nonce-aaa", require_binding=True))

        # Hapus cache RAM _CONSUMED_OAUTH_STATES untuk simulasi restart/multi-instance -> tetap ditolak oleh DB!
        with google_auth._OAUTH_STATE_LOCK:
            google_auth._CONSUMED_OAUTH_STATES.clear()
        self.assertFalse(google_auth.verify_oauth_state(st_a, browser_binding="browser-nonce-aaa", require_binding=True))

    def test_07_medium02_medium03_webhook_hardening_and_login_lockout(self):
        # 1. Midtrans capture + fraud_status=challenge TIDAK boleh melunaskan order
        ord_mid = db_history.create_payment_order(self.test_uid, "PRO_30D", 19000, 30, provider="midtrans_snap")
        sig_chal = hashlib.sha512(f"{ord_mid['order_id']}20019000.00SB-Mid-KEY".encode()).hexdigest()
        with patch.dict(os.environ, {"MIDTRANS_SERVER_KEY": "SB-Mid-KEY"}, clear=False):
            ok_c, code_c, _ = payment_gateway.process_midtrans_notification({
                "order_id": ord_mid["order_id"],
                "status_code": "200",
                "gross_amount": "19000.00",
                "signature_key": sig_chal,
                "transaction_status": "capture",
                "fraud_status": "challenge",
            })
        self.assertTrue(ok_c)
        self.assertEqual(code_c, 200)
        self.assertFalse(db_history.get_user_scan_status(self.test_uid)["is_pro"])

        # 2. Mayar webhook tanpa amount wajib fail-closed (400); status failed diabaikan
        ord_my = db_history.create_payment_order(self.test_uid, "PRO_7D", 9000, 7, provider="mayar_api")
        with patch.dict(os.environ, {"MAYAR_WEBHOOK_TOKEN": "tok-sec"}, clear=False):
            ok_na, code_na, _ = payment_gateway.process_mayar_webhook(
                {"event": "payment.received", "data": {"order_id": ord_my["order_id"]}},
                supplied_token="tok-sec",
            )
            self.assertFalse(ok_na)
            self.assertEqual(code_na, 400)

            ok_fl, code_fl, _ = payment_gateway.process_mayar_webhook(
                {"event": "payment.received", "data": {"order_id": ord_my["order_id"], "amount": 9000, "status": "failed"}},
                supplied_token="tok-sec",
            )
            self.assertTrue(ok_fl)
            self.assertEqual(code_fl, 200)
            self.assertFalse(db_history.get_user_scan_status(self.test_uid)["is_pro"])

        # 3. whatsapp_bot.py tidak menerima secret token di query string URL
        with open(os.path.join(ROOT_DIR, "whatsapp_bot.py"), "r", encoding="utf-8") as fh:
            bot_src = fh.read()
        self.assertNotIn('query_params.get("token")', bot_src)

        # 4. Login lockout & pesan error seragam (anti enumerasi)
        _, msg_missing = db_history.authenticate_user("tidak_ada_sama_sekali@example.com", "9999")
        _, msg_wrong = db_history.authenticate_user(self.test_uid, "9999")
        self.assertEqual(msg_missing, msg_wrong)
        for _ in range(4):
            ok_att, msg_att = db_history.authenticate_user(self.test_uid, "9999")
            self.assertFalse(ok_att)
        # Percobaan ke-6 bahkan dengan PIN BENAR harus diblokir saat akun terkunci
        ok_locked, msg_locked = db_history.authenticate_user(self.test_uid, "1234")
        self.assertFalse(ok_locked)
        self.assertIn("kunci", msg_locked.lower())

    def test_08_low01_low02_markdown_guard_dockerignore_and_telegram_alert(self):
        # 1. Blokir Markdown image/link pada nama makanan (pending_foods / input teks)
        with self.assertRaises(fg.FoodGuardrailRejected):
            fg.validate_food_text_query("Roti Tawar ![ping](https://attacker.test/log)")

        # 2. .dockerignore melindungi secrets & file log
        with open(os.path.join(ROOT_DIR, ".dockerignore"), "r", encoding="utf-8") as fh:
            di_txt = fh.read()
        self.assertIn(".streamlit/secrets.toml", di_txt)
        self.assertIn(".env.*", di_txt)

        # 3. Telegram send_alert_to_phone benar-benar terpanggil saat webhook QRIS lunas
        ord_ok = db_history.create_payment_order(self.test_uid, "PRO_7D", 9000, 7, provider="midtrans_snap")
        sig_ok = hashlib.sha512(f"{ord_ok['order_id']}2009000.00SB-Mid-KEY".encode()).hexdigest()
        with patch.dict(os.environ, {"MIDTRANS_SERVER_KEY": "SB-Mid-KEY"}, clear=False):
            with patch.object(payment_gateway, "send_alert_to_phone") as mock_tg:
                ok_p, code_p, _ = payment_gateway.process_midtrans_notification({
                    "order_id": ord_ok["order_id"],
                    "status_code": "200",
                    "gross_amount": "9000.00",
                    "signature_key": sig_ok,
                    "transaction_status": "settlement",
                    "fraud_status": "accept",
                    "transaction_id": "tx-alert-ok",
                })
                self.assertTrue(ok_p)
                self.assertEqual(code_p, 200)
                mock_tg.assert_called_once()


if __name__ == "__main__":
    unittest.main()

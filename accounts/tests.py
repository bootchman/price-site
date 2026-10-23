import json
import tempfile
from datetime import timedelta
from pathlib import Path

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts import access
from accounts.models import LoginToken
from accounts.services import DENY_EXPIRED, DENY_FOREIGN_CONTACT, DENY_NOT_IN_LIST, confirm_login, create_login_token

TMP = Path(tempfile.mkdtemp())
ALLOWED = TMP / "allowed.json"
EVENTS = TMP / "auth_events.jsonl"


def write_allowed(entries):
    ALLOWED.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    access._cache["mtime"] = None


@override_settings(ACCESS_LIST_FILE=ALLOWED, AUTH_EVENTS_FILE=EVENTS)
class AccessTests(TestCase):
    def setUp(self):
        write_allowed([{"phone": "380663341966", "nick": "@VarEg14", "row": 2}])

    def test_phone_with_plus_and_spaces(self):
        self.assertTrue(access.is_allowed("+380 66 334 19 66"))

    def test_phone_without_country_code(self):
        self.assertTrue(access.is_allowed("0663341966"))

    def test_nick_fallback_case_insensitive(self):
        self.assertTrue(access.is_allowed("", "vareg14"))

    def test_unknown(self):
        self.assertFalse(access.is_allowed("380991112233", "someone"))

    def test_missing_file_denies_everyone(self):
        ALLOWED.unlink()
        access._cache.update(mtime=None, entries=[])
        self.assertFalse(access.is_allowed("380663341966"))


@override_settings(ACCESS_LIST_FILE=ALLOWED, AUTH_EVENTS_FILE=EVENTS)
class LoginFlowTests(TestCase):
    def setUp(self):
        write_allowed([{"phone": "380663341966", "nick": "", "row": 2}])
        if EVENTS.exists():
            EVENTS.unlink()

    def start_login(self):
        resp = self.client.post("/login/start/")
        self.assertEqual(resp.status_code, 200)
        token = resp.json()["link"].split("start=login_")[1]
        return token

    def test_full_login(self):
        token = self.start_login()
        self.assertEqual(self.client.get("/login/status/").json()["status"], "pending")
        ok, _ = confirm_login(token, 555, 555, "+380663341966", "alex", "Alex")
        self.assertTrue(ok)
        resp = self.client.get("/login/status/").json()
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(self.client.get("/").status_code, 200)
        event = json.loads(EVENTS.read_text(encoding="utf-8").strip())
        self.assertEqual((event["row"], event["telegram_id"]), (2, 555))
        # Код одноразовый
        self.assertEqual(self.client.get("/login/status/").json()["status"], "none")

    def test_not_in_list(self):
        token = self.start_login()
        ok, text = confirm_login(token, 556, 556, "380991112233", "", "X")
        self.assertEqual((ok, text), (False, DENY_NOT_IN_LIST))
        self.assertEqual(self.client.get("/login/status/").json()["status"], "denied")

    def test_foreign_contact(self):
        token = self.start_login()
        ok, text = confirm_login(token, 557, 999, "380663341966", "", "X")
        self.assertEqual((ok, text), (False, DENY_FOREIGN_CONTACT))

    def test_expired_token(self):
        login = create_login_token("s")
        LoginToken.objects.filter(pk=login.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        ok, text = confirm_login(login.token, 558, 558, "380663341966", "", "X")
        self.assertEqual((ok, text), (False, DENY_EXPIRED))

    def test_token_of_other_session_cannot_be_redeemed(self):
        token = self.start_login()
        confirm_login(token, 559, 559, "380663341966", "", "X")
        other = self.client_class()
        self.assertEqual(other.get("/login/status/").json()["status"], "none")

    def test_removed_from_list_is_logged_out(self):
        token = self.start_login()
        confirm_login(token, 560, 560, "380663341966", "", "X")
        self.client.get("/login/status/")
        self.assertEqual(self.client.get("/").status_code, 200)
        write_allowed([])
        resp = self.client.get("/")
        self.assertRedirects(resp, "/login/", fetch_redirect_response=False)

    def test_login_start_with_real_csrf(self):
        client = self.client_class(enforce_csrf_checks=True)
        client.get("/login/")
        csrf = client.cookies["csrftoken"].value
        resp = client.post("/login/start/", HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("start=login_", resp.json()["link"])

    def test_anonymous_redirected(self):
        self.assertRedirects(self.client.get("/"), "/login/", fetch_redirect_response=False)

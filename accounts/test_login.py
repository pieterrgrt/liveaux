"""Logging in, signing up, logging out and passwords, with and without a mail server."""

import importlib.util
import os
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import User

PASSWORD = "a-long-Passw0rd!"


def load_settings(**env):
    """A fresh copy of config/settings.py, read with these environment variables."""
    path = Path(settings.BASE_DIR) / "config" / "settings.py"
    spec = importlib.util.spec_from_file_location("settings_under_test", path)
    module = importlib.util.module_from_spec(spec)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("EMAIL_", "ACCOUNT_"))}
    with mock.patch.dict(os.environ, {**clean, "DJANGO_DEBUG": "1", **env}, clear=True):
        spec.loader.exec_module(module)
    return module


class MailSettingsTests(TestCase):
    def test_placeholder_host_counts_as_no_mail_server(self):
        for host in ("", "smtp.example.com", "example.com", "mail.example.org", "SMTP.EXAMPLE.COM"):
            with self.subTest(host=host):
                s = load_settings(EMAIL_HOST=host)
                self.assertFalse(s.EMAIL_IS_CONFIGURED)
                self.assertEqual(s.EMAIL_BACKEND, "django.core.mail.backends.console.EmailBackend")
                self.assertEqual(s.ACCOUNT_EMAIL_VERIFICATION, "optional")

    def test_real_host_means_smtp_and_mandatory_confirmation(self):
        s = load_settings(EMAIL_HOST="smtp.fastmail.com", EMAIL_HOST_USER="me", EMAIL_HOST_PASSWORD="pw")
        self.assertTrue(s.EMAIL_IS_CONFIGURED)
        self.assertEqual(s.EMAIL_BACKEND, "django.core.mail.backends.smtp.EmailBackend")
        self.assertEqual(s.EMAIL_HOST, "smtp.fastmail.com")
        self.assertEqual(s.ACCOUNT_EMAIL_VERIFICATION, "mandatory")

    def test_verification_can_be_set(self):
        self.assertEqual(load_settings(ACCOUNT_EMAIL_VERIFICATION="none").ACCOUNT_EMAIL_VERIFICATION, "none")
        self.assertEqual(
            load_settings(EMAIL_HOST="smtp.fastmail.com", ACCOUNT_EMAIL_VERIFICATION="Optional").ACCOUNT_EMAIL_VERIFICATION,
            "optional",
        )
        # Nonsense falls back to the default.
        self.assertEqual(load_settings(ACCOUNT_EMAIL_VERIFICATION="sometimes").ACCOUNT_EMAIL_VERIFICATION, "optional")

    def test_long_remembered_sessions(self):
        s = load_settings()
        self.assertTrue(s.ACCOUNT_SESSION_REMEMBER)
        self.assertGreaterEqual(s.SESSION_COOKIE_AGE, 60 * 60 * 24 * 180)


@override_settings(ACCOUNT_EMAIL_VERIFICATION="optional")
class LoginFlowTests(TestCase):
    def test_sign_up_and_go_straight_in(self):
        response = self.client.post(
            reverse("account_signup"), {"email": "new@example.com", "password1": PASSWORD, "password2": PASSWORD}
        )
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "My liveaux")

    def test_log_in_stays_remembered_and_log_out(self):
        User.objects.create_user("fan@example.com", PASSWORD)  # an address nobody ever confirmed
        response = self.client.post(reverse("account_login"), {"login": "fan@example.com", "password": PASSWORD})
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertGreater(self.client.session.get_expiry_age(), 60 * 60 * 24 * 180)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

        response = self.client.post(reverse("account_logout"))
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

    def test_wrong_password(self):
        User.objects.create_user("fan@example.com", PASSWORD)
        response = self.client.post(reverse("account_login"), {"login": "fan@example.com", "password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_change_password(self):
        user = User.objects.create_user("fan@example.com", PASSWORD)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("account_change_password")).status_code, 200)
        response = self.client.post(
            reverse("account_change_password"),
            {"oldpassword": PASSWORD, "password1": "another-Passw0rd!", "password2": "another-Passw0rd!"},
        )
        self.assertEqual(response.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.check_password("another-Passw0rd!"))
        self.assertIn("_auth_user_id", self.client.session)  # still logged in after the change

    @override_settings(EMAIL_CAN_SEND=False)
    def test_password_reset_without_a_mail_server_says_so(self):
        User.objects.create_user("fan@example.com", PASSWORD)
        response = self.client.post(reverse("account_reset_password"), {"email": "fan@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "can&#x27;t send email yet")
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_CAN_SEND=True)
    def test_password_reset_with_mail(self):
        User.objects.create_user("fan@example.com", PASSWORD)
        response = self.client.post(reverse("account_reset_password"), {"email": "fan@example.com"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/]+(/account/password/reset/key/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(link, follow=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            response.redirect_chain[-1][0] if response.redirect_chain else link,
            {"password1": "another-Passw0rd!", "password2": "another-Passw0rd!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.get().check_password("another-Passw0rd!"))

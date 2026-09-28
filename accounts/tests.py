import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from .models import User


class SignupTests(TestCase):
    def test_signup_confirm_email_and_reach_dashboard(self):
        response = self.client.post(
            reverse("account_signup"),
            {"email": "fan@example.com", "password1": "a-long-Passw0rd!", "password2": "a-long-Passw0rd!"},
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="fan@example.com")
        self.assertFalse(user.emailaddress_set.get().verified)

        # Not logged in until the email address is confirmed.
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

        self.assertEqual(len(mail.outbox), 1)
        confirm_url = re.search(r"https?://[^/]+(/account/confirm-email/\S+)", mail.outbox[0].body).group(1)
        response = self.client.post(confirm_url)
        self.assertRedirects(response, reverse("accounts:dashboard"))
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "My liveaux")

    def test_login_with_email(self):
        user = User.objects.create_user("fan@example.com", "a-long-Passw0rd!")
        user.emailaddress_set.create(email=user.email, primary=True, verified=True)
        response = self.client.post(
            reverse("account_login"), {"login": "fan@example.com", "password": "a-long-Passw0rd!"}
        )
        self.assertRedirects(response, reverse("accounts:dashboard"))

    def test_create_superuser_without_username(self):
        admin = User.objects.create_superuser("admin@example.com", "pw")
        self.assertTrue(admin.is_staff)
        self.assertEqual(admin.get_username(), "admin@example.com")


class SettingsTests(TestCase):
    def test_change_display_name(self):
        user = User.objects.create_user("fan@example.com", "pw")
        self.client.force_login(user)
        self.client.post(reverse("accounts:settings"), {"display_name": "Pieter"})
        user.refresh_from_db()
        self.assertEqual(user.display_name, "Pieter")
        self.assertEqual(str(user), "Pieter")

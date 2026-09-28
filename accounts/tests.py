import re
from datetime import timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Category, City, Event, Venue
from logbook.models import LogEntry

from .models import User


def music():
    return Category.objects.get(slug="music")  # created by a migration


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


class PrivacyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("fan@example.com", "a-long-Passw0rd!")
        self.user.emailaddress_set.create(email=self.user.email, primary=True, verified=True)
        venue = Venue.objects.create(name="SO36", city=City.objects.create(name="Berlin", slug="berlin"))
        self.event = Event.objects.create(category=music(), title="Punk Night", venue=venue, starts_at=timezone.now() - timedelta(days=1))
        LogEntry.objects.create(user=self.user, event=self.event, rating=8, note="Loud")
        venue.memberships.create(user=self.user, role="owner")
        self.client.force_login(self.user)

    def test_privacy_page(self):
        self.client.logout()
        response = self.client.get(reverse("privacy"))
        self.assertContains(response, "private by default")
        self.assertContains(response, "privacy@liveaux.eu")

    def test_export(self):
        response = self.client.get(reverse("accounts:export"))
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="liveaux-data.json"')
        data = response.json()
        self.assertEqual(data["account"]["email"], "fan@example.com")
        self.assertEqual(data["log"][0]["note"], "Loud")
        self.assertEqual(data["manages"]["venues"], ["SO36"])

    def test_delete_needs_password(self):
        response = self.client.post(reverse("accounts:delete"), {"password": "wrong", "confirm": "on"})
        self.assertContains(response, "not your password")
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_delete_account_removes_everything(self):
        response = self.client.post(reverse("accounts:delete"), {"password": "a-long-Passw0rd!", "confirm": "on"})
        self.assertRedirects(response, "/")
        self.assertFalse(User.objects.exists())
        self.assertFalse(LogEntry.objects.exists())
        self.assertFalse(self.event.venue.memberships.exists())
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

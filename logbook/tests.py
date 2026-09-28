from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Artist, City, Event, Venue

from .models import LogEntry


def local(*args):
    return timezone.make_aware(datetime(*args))


class LogbookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fan = User.objects.create_user("fan@example.com", "pw", display_name="Pieter")
        cls.other = User.objects.create_user("other@example.com", "pw")
        city = City.objects.create(name="Berlin", slug="berlin")
        cls.venue = Venue.objects.create(name="SO36", city=city)
        cls.past = Event.objects.create(title="Punk Night", venue=cls.venue, starts_at=timezone.now() - timedelta(days=2))
        cls.future = Event.objects.create(title="Next Week", venue=cls.venue, starts_at=timezone.now() + timedelta(days=7))

    def setUp(self):
        self.client.force_login(self.fan)

    def test_i_was_there(self):
        response = self.client.get(self.past.get_absolute_url())
        self.assertContains(response, "I was there")
        response = self.client.post(reverse("logbook:attended", args=[self.past.pk]))
        entry = LogEntry.objects.get()
        self.assertRedirects(response, entry.get_edit_url())
        # Pressing it twice doesn't make a second entry.
        self.client.post(reverse("logbook:attended", args=[self.past.pk]))
        self.assertEqual(LogEntry.objects.count(), 1)
        self.assertContains(self.client.get(self.past.get_absolute_url()), "You were there ✓")

    def test_cannot_log_future_event(self):
        self.assertNotContains(self.client.get(self.future.get_absolute_url()), "I was there")
        self.client.post(reverse("logbook:attended", args=[self.future.pk]))
        self.assertFalse(LogEntry.objects.exists())

    def test_rate_note_and_delete(self):
        entry = LogEntry.objects.create(user=self.fan, event=self.past)
        self.client.post(entry.get_edit_url(), {"rating": "9", "note": "Loud and sweaty."})
        entry.refresh_from_db()
        self.assertEqual((entry.rating, entry.note), (9, "Loud and sweaty."))
        self.assertContains(self.client.get(reverse("logbook:mine")), "Loud and sweaty.")
        self.client.post(reverse("logbook:delete", args=[entry.pk]))
        self.assertFalse(LogEntry.objects.exists())

    def test_rating_must_be_1_to_10(self):
        entry = LogEntry.objects.create(user=self.fan, event=self.past)
        self.client.post(entry.get_edit_url(), {"rating": "11", "note": ""})
        entry.refresh_from_db()
        self.assertIsNone(entry.rating)

    def test_cannot_touch_someone_elses_entry(self):
        entry = LogEntry.objects.create(user=self.other, event=self.past, note="secret")
        self.assertEqual(self.client.get(entry.get_edit_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("logbook:delete", args=[entry.pk])).status_code, 404)
        self.assertTrue(LogEntry.objects.exists())

    def test_log_is_private_by_default(self):
        LogEntry.objects.create(user=self.fan, event=self.past, note="secret")
        self.assertFalse(self.fan.log_is_public)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("logbook:public", args=[self.fan.pk])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("logbook:public_year", args=[self.fan.pk, self.past.starts_at.year])).status_code,
            404,
        )
        self.client.logout()
        self.assertEqual(self.client.get(reverse("logbook:public", args=[self.fan.pk])).status_code, 404)
        self.assertRedirects(
            self.client.get(reverse("logbook:mine")), f"{reverse('account_login')}?next={reverse('logbook:mine')}"
        )

    def test_public_log_hides_email(self):
        LogEntry.objects.create(user=self.fan, event=self.past, note="Great night")
        self.client.post(reverse("accounts:settings"), {"display_name": "Pieter", "log_is_public": "on"})
        self.client.logout()
        response = self.client.get(reverse("logbook:public", args=[self.fan.pk]))
        self.assertContains(response, "Pieter")
        self.assertContains(response, "Great night")
        self.assertNotContains(response, "fan@example.com")
        self.assertNotContains(response, "Edit")

    def test_attended_needs_post_and_login(self):
        url = reverse("logbook:attended", args=[self.past.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertRedirects(self.client.post(url), f"{reverse('account_login')}?next={url}")

    def test_dashboard_asks_about_saved_past_shows(self):
        self.past.saved_by.add(self.fan)
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Were you there?")
        LogEntry.objects.create(user=self.fan, event=self.past)
        self.assertNotContains(self.client.get(reverse("accounts:dashboard")), "Were you there?")


class YearTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fan = User.objects.create_user("fan@example.com", "pw")
        city = City.objects.create(name="Berlin", slug="berlin")
        so36 = Venue.objects.create(name="SO36", city=city)
        lido = Venue.objects.create(name="Lido", city=city)
        molotow = Venue.objects.create(name="Molotow", city=City.objects.create(name="Hamburg", slug="hamburg"))
        band = Artist.objects.create(name="Die Ärzte")
        shows = [
            ("One", so36, local(2025, 3, 1, 20), 8),
            ("Two", so36, local(2025, 3, 20, 20), 6),
            ("Three", lido, local(2025, 7, 4, 20), None),
            ("Four", molotow, local(2025, 12, 31, 23, 30), 10),  # 22:30 UTC: still 2025 in Berlin
            ("Other year", so36, local(2024, 5, 1, 20), 7),
        ]
        for title, venue, starts_at, rating in shows:
            event = Event.objects.create(title=title, venue=venue, starts_at=starts_at)
            event.artists.add(band)
            LogEntry.objects.create(user=cls.fan, event=event, rating=rating)

    def test_year_overview(self):
        self.client.force_login(self.fan)
        response = self.client.get(reverse("logbook:my_year", args=[2025]))
        stats = response.context["stats"]
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["venue_count"], 3)
        self.assertEqual(stats["city_count"], 2)
        self.assertEqual(stats["average_rating"], 8.0)
        self.assertEqual(stats["top_venues"][0][0].name, "SO36")
        self.assertEqual(stats["top_artists"][0][1], 4)
        self.assertEqual([e.event.title for e in stats["best"]], ["Four", "One", "Two"])
        self.assertEqual(stats["months"][2]["count"], 2)
        self.assertEqual(stats["months"][2]["percent"], 100)
        self.assertNotContains(response, "Other year")
        self.assertContains(response, 'href="/me/log/2024/"')

    def test_empty_year(self):
        self.client.force_login(self.fan)
        self.assertContains(self.client.get(reverse("logbook:my_year", args=[2010])), "No shows logged in 2010")

    def test_public_year(self):
        self.fan.log_is_public = True
        self.fan.save()
        response = self.client.get(reverse("logbook:public_year", args=[self.fan.pk, 2025]))
        self.assertContains(response, "A liveaux fan")
        self.assertEqual(self.client.get(reverse("logbook:public_year", args=[self.fan.pk, 2010])).status_code, 404)

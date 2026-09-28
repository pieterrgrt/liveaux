from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Event, Venue


class FrontendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.so36 = Venue.objects.create(name="SO36", district="Kreuzberg")
        cls.kesselhaus = Venue.objects.create(name="Kesselhaus", district="Prenzlauer Berg")
        cls.upcoming = Event.objects.create(title="Punk Night", venue=cls.so36, starts_at=now + timedelta(days=3))
        cls.other = Event.objects.create(title="Folk Evening", venue=cls.kesselhaus, starts_at=now + timedelta(days=5))
        cls.past = Event.objects.create(title="Old Show", venue=cls.so36, starts_at=now - timedelta(days=3))

    def test_list_shows_only_upcoming_events(self):
        response = self.client.get(reverse("events:event_list"))
        self.assertContains(response, "Punk Night")
        self.assertContains(response, "Folk Evening")
        self.assertNotContains(response, "Old Show")

    def test_list_filters_by_district(self):
        response = self.client.get(reverse("events:event_list"), {"district": "Kreuzberg"})
        self.assertContains(response, "Punk Night")
        self.assertNotContains(response, "Folk Evening")

    def test_event_detail(self):
        response = self.client.get(self.upcoming.get_absolute_url())
        self.assertContains(response, "Punk Night")
        self.assertContains(response, "SO36")

    def test_venue_detail(self):
        response = self.client.get(self.so36.get_absolute_url())
        self.assertContains(response, "Punk Night")
        self.assertNotContains(response, "Old Show")

    def test_unknown_event_is_404(self):
        response = self.client.get(reverse("events:event_detail", args=[999]))
        self.assertEqual(response.status_code, 404)

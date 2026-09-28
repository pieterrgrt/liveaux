from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Artist, Event, Membership, Promoter, Venue


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
        self.assertContains(response, "Log in to save")

    def test_venue_detail(self):
        response = self.client.get(self.so36.get_absolute_url())
        self.assertContains(response, "Punk Night")
        self.assertNotContains(response, "Old Show")

    def test_unknown_event_is_404(self):
        response = self.client.get(reverse("events:event_detail", args=[999]))
        self.assertEqual(response.status_code, 404)


class FanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fan = User.objects.create_user("fan@example.com", "pw")
        cls.venue = Venue.objects.create(name="SO36", district="Kreuzberg")
        cls.artist = Artist.objects.create(name="Die Ärzte")
        cls.event = Event.objects.create(
            title="Punk Night", venue=cls.venue, starts_at=timezone.now() + timedelta(days=3)
        )
        cls.gig = Event.objects.create(
            title="Ärzte live", venue=Venue.objects.create(name="Lido"), starts_at=timezone.now() + timedelta(days=4)
        )
        cls.gig.artists.add(cls.artist)

    def setUp(self):
        self.client.force_login(self.fan)

    def test_save_and_unsave_event(self):
        url = reverse("events:toggle_save", args=[self.event.pk])
        self.client.post(url)
        self.assertTrue(self.event.saved_by.filter(pk=self.fan.pk).exists())
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Punk Night")
        self.client.post(url)
        self.assertFalse(self.event.saved_by.filter(pk=self.fan.pk).exists())

    def test_follow_artist_shows_their_events_on_dashboard(self):
        self.client.post(reverse("events:toggle_follow", args=["artist", self.artist.pk]))
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertContains(response, "Ärzte live")
        self.assertNotContains(response, "Punk Night")

    def test_toggles_need_post_and_login(self):
        url = reverse("events:toggle_save", args=[self.event.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertRedirects(self.client.post(url), f"{reverse('account_login')}?next={url}")

    def test_next_redirect_stays_on_site(self):
        url = reverse("events:toggle_save", args=[self.event.pk])
        response = self.client.post(url, {"next": "//evil.example.com/"})
        self.assertRedirects(response, self.event.get_absolute_url())


class ManageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner@so36.de", "pw")
        cls.editor = User.objects.create_user("editor@so36.de", "pw")
        cls.stranger = User.objects.create_user("stranger@example.com", "pw")
        cls.venue = Venue.objects.create(name="SO36", district="Kreuzberg")
        cls.other_venue = Venue.objects.create(name="Lido")
        cls.venue.memberships.create(user=cls.owner, role=Membership.OWNER)
        cls.venue.memberships.create(user=cls.editor, role=Membership.EDITOR)

    def event_data(self, **extra):
        data = {"title": "Punk Night", "starts_at": "2030-10-02T20:00", "price": "18", "ticket_url": "", "description": ""}
        data.update(extra)
        return data

    def test_stranger_cannot_manage(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(reverse("events:manage_page", args=["venue", self.venue.pk])).status_code, 403)
        response = self.client.post(reverse("events:create_event", args=["venue", self.venue.pk]), self.event_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Event.objects.exists())

    def test_venue_editor_creates_event_at_own_venue(self):
        self.client.force_login(self.editor)
        # A venue field in the POST is ignored: the event always belongs to the managed venue.
        self.client.post(
            reverse("events:create_event", args=["venue", self.venue.pk]),
            self.event_data(venue=self.other_venue.pk),
        )
        event = Event.objects.get()
        self.assertEqual(event.venue, self.venue)
        self.assertEqual(event.created_by, self.editor)

    def test_promoter_picks_venue(self):
        promoter = Promoter.objects.create(name="Kreuzberg Nights")
        promoter.memberships.create(user=self.stranger, role=Membership.OWNER)
        self.client.force_login(self.stranger)
        self.client.post(
            reverse("events:create_event", args=["promoter", promoter.pk]),
            self.event_data(venue=self.other_venue.pk),
        )
        event = Event.objects.get()
        self.assertEqual((event.venue, event.promoter), (self.other_venue, promoter))
        self.assertTrue(event.can_edit(self.stranger))
        self.assertFalse(event.can_edit(self.owner))

    def test_edit_and_delete_event(self):
        event = Event.objects.create(title="Old title", venue=self.venue, starts_at=timezone.now() + timedelta(days=1))
        self.client.force_login(self.editor)
        self.client.post(reverse("events:edit_event", args=[event.pk]), self.event_data(title="New title"))
        event.refresh_from_db()
        self.assertEqual(event.title, "New title")
        self.client.post(reverse("events:delete_event", args=[event.pk]))
        self.assertFalse(Event.objects.exists())

    def test_users_create_artist_pages_but_not_venues(self):
        self.client.force_login(self.stranger)
        self.client.post(reverse("events:create_page", args=["artist"]), {"name": "Die Ärzte", "hometown": "Berlin"})
        artist = Artist.objects.get()
        self.assertTrue(artist.membership_for(self.stranger).is_owner)
        self.assertEqual(self.client.get(reverse("events:create_page", args=["venue"])).status_code, 404)

    def test_owner_adds_member_editor_cannot(self):
        url = reverse("events:add_member", args=["venue", self.venue.pk])
        self.client.force_login(self.editor)
        self.assertEqual(self.client.post(url, {"email": "stranger@example.com", "role": "editor"}).status_code, 403)
        self.client.force_login(self.owner)
        self.client.post(url, {"email": "STRANGER@example.com", "role": "editor"})
        self.assertTrue(self.venue.is_member(self.stranger))

    def test_last_owner_cannot_be_removed(self):
        admin = User.objects.create_superuser("admin@example.com", "pw")
        self.client.force_login(admin)
        owner_membership = self.venue.memberships.get(user=self.owner)
        self.client.post(reverse("events:remove_member", args=["venue", self.venue.pk, owner_membership.pk]))
        self.assertTrue(self.venue.is_member(self.owner))

    def test_unknown_kind_is_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("events:manage_page", args=["band", 1])).status_code, 404)

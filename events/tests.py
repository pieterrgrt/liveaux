from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from .models import Artist, Category, City, Event, EventSubmission, Membership, Promoter, Venue


def music():
    return Category.objects.get(slug="music")  # created by a migration


def berlin():
    return City.objects.get_or_create(slug="berlin", defaults={"name": "Berlin"})[0]


class FrontendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.so36 = Venue.objects.create(city=berlin(), name="SO36", district="Kreuzberg")
        cls.kesselhaus = Venue.objects.create(city=berlin(), name="Kesselhaus", district="Prenzlauer Berg")
        cls.upcoming = Event.objects.create(category=music(), title="Punk Night", venue=cls.so36, starts_at=now + timedelta(days=3))
        cls.other = Event.objects.create(category=music(), title="Folk Evening", venue=cls.kesselhaus, starts_at=now + timedelta(days=5))
        cls.past = Event.objects.create(category=music(), title="Old Show", venue=cls.so36, starts_at=now - timedelta(days=3))

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
        cls.venue = Venue.objects.create(city=berlin(), name="SO36", district="Kreuzberg")
        cls.artist = Artist.objects.create(name="Die Ärzte")
        cls.event = Event.objects.create(category=music(), 
            title="Punk Night", venue=cls.venue, starts_at=timezone.now() + timedelta(days=3)
        )
        cls.gig = Event.objects.create(category=music(), 
            title="Ärzte live", venue=Venue.objects.create(city=berlin(), name="Lido"), starts_at=timezone.now() + timedelta(days=4)
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
        cls.venue = Venue.objects.create(city=berlin(), name="SO36", district="Kreuzberg")
        cls.other_venue = Venue.objects.create(city=berlin(), name="Lido")
        cls.venue.memberships.create(user=cls.owner, role=Membership.OWNER)
        cls.venue.memberships.create(user=cls.editor, role=Membership.EDITOR)

    def event_data(self, **extra):
        data = {
            "title": "Punk Night",
            "category": music().pk,
            "starts_at": "2030-10-02T20:00",
            "price": "18",
            "ticket_url": "",
            "description": "",
        }
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
        event = Event.objects.create(category=music(), title="Old title", venue=self.venue, starts_at=timezone.now() + timedelta(days=1))
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


class CityWeekTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.hamburg = City.objects.create(name="Hamburg", slug="hamburg")
        so36 = Venue.objects.create(city=berlin(), name="SO36", district="Kreuzberg")
        molotow = Venue.objects.create(city=cls.hamburg, name="Molotow", district="St. Pauli")
        Event.objects.create(category=music(), title="Punk Night", venue=so36, starts_at=now + timedelta(days=2))
        Event.objects.create(category=music(), title="Next Month", venue=so36, starts_at=now + timedelta(days=30))
        Event.objects.create(category=music(), title="Yesterday", venue=so36, starts_at=now - timedelta(days=1))
        Event.objects.create(category=music(), title="Garage Night", venue=molotow, starts_at=now + timedelta(days=2))

    def test_week_shows_only_this_city_and_week(self):
        response = self.client.get(reverse("events:city_week", args=["berlin"]))
        self.assertContains(response, "This week<br>in <em>Berlin.</em>", html=False)
        self.assertContains(response, "Punk Night")
        self.assertNotContains(response, "Next Month")
        self.assertNotContains(response, "Yesterday")
        self.assertNotContains(response, "Garage Night")
        self.assertContains(response, 'href="/week/hamburg/"')

    def test_week_redirects_to_first_city(self):
        self.assertRedirects(self.client.get(reverse("events:this_week")), reverse("events:city_week", args=["berlin"]))

    def test_unknown_city_is_404(self):
        self.assertEqual(self.client.get(reverse("events:city_week", args=["paris"])).status_code, 404)

    def test_list_filters_by_city(self):
        response = self.client.get(reverse("events:event_list"), {"city": "hamburg"})
        self.assertContains(response, "Garage Night")
        self.assertNotContains(response, "Punk Night")
        self.assertContains(response, "St. Pauli")
        self.assertNotContains(response, "Kreuzberg")


class SubmissionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.booker = User.objects.create_user("booker@example.com", "pw")
        cls.admin = User.objects.create_superuser("admin@example.com", "pw")
        cls.venue = Venue.objects.create(city=berlin(), name="SO36")

    def data(self, **extra):
        data = {
            "title": "Punk Night",
            "category": music().pk,
            "starts_at": "2030-10-02T20:00",
            "relation": "Booker",
            "price": "12",
        }
        data.update(extra)
        return data

    def test_needs_login(self):
        response = self.client.get(reverse("events:submit_event"))
        self.assertRedirects(response, f"{reverse('account_login')}?next={reverse('events:submit_event')}")

    def test_submission_waits_for_approval(self):
        self.client.force_login(self.booker)
        response = self.client.post(reverse("events:submit_event"), self.data(venue=self.venue.pk))
        self.assertRedirects(response, reverse("accounts:dashboard"))
        submission = EventSubmission.objects.get()
        self.assertEqual((submission.submitted_by, submission.status), (self.booker, EventSubmission.PENDING))
        self.assertFalse(Event.objects.exists())
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Waiting for review")

    def test_venue_or_new_venue_required(self):
        self.client.force_login(self.booker)
        response = self.client.post(reverse("events:submit_event"), self.data())
        self.assertContains(response, "Pick a venue above")
        response = self.client.post(reverse("events:submit_event"), self.data(venue=self.venue.pk, starts_at="2020-01-01T20:00"))
        self.assertContains(response, "in the past")
        self.assertFalse(EventSubmission.objects.exists())

    def test_admin_approves_new_venue(self):
        self.client.force_login(self.booker)
        self.client.post(
            reverse("events:submit_event"),
            self.data(new_venue_name="Cassiopeia", new_venue_district="Friedrichshain", new_venue_city=berlin().pk),
        )
        submission = EventSubmission.objects.get()
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin:events_eventsubmission_changelist"),
            {"action": "approve", "_selected_action": [submission.pk]},
        )
        submission.refresh_from_db()
        event = Event.objects.get()
        self.assertEqual(submission.status, EventSubmission.APPROVED)
        self.assertEqual(submission.event, event)
        self.assertEqual((event.venue.name, event.venue.city, event.created_by), ("Cassiopeia", berlin(), self.booker))
        self.assertFalse(event.can_edit(self.booker))  # venue access is still granted by hand

    def test_admin_rejects(self):
        submission = EventSubmission.objects.create(category=music(), 
            submitted_by=self.booker, venue=self.venue, title="Spam", starts_at=timezone.now(), relation="x"
        )
        self.client.force_login(self.admin)
        self.client.post(
            reverse("admin:events_eventsubmission_changelist"),
            {"action": "reject", "_selected_action": [submission.pk]},
        )
        submission.refresh_from_db()
        self.assertEqual(submission.status, EventSubmission.REJECTED)
        self.assertFalse(Event.objects.exists())
        with self.assertRaises(ValueError):
            submission.approve()


class CategoryAndRunTests(TestCase):
    """Events of every kind, and ones that run for days (exhibitions, festivals)."""

    @classmethod
    def setUpTestData(cls):
        now = timezone.now()
        cls.exhibition = Category.objects.get(slug="exhibition")
        museum = Venue.objects.create(city=berlin(), name="Neue Nationalgalerie", district="Tiergarten")
        club = Venue.objects.create(city=berlin(), name="SO36", district="Kreuzberg")
        cls.running = Event.objects.create(
            category=cls.exhibition,
            title="Farbe als Raum",
            venue=museum,
            starts_at=now - timedelta(days=30),
            ends_at=now + timedelta(days=60),
        )
        Event.objects.create(
            category=cls.exhibition,
            title="Closed Show",
            venue=museum,
            starts_at=now - timedelta(days=90),
            ends_at=now - timedelta(days=1),
        )
        Event.objects.create(category=music(), title="Punk Night", venue=club, starts_at=now + timedelta(days=2))

    def test_running_exhibition_is_on_now(self):
        response = self.client.get(reverse("events:event_list"))
        self.assertContains(response, "On now")
        self.assertEqual([e.title for e in response.context["on_now"]], ["Farbe als Raum"])
        self.assertEqual([e.title for e in response.context["events"]], ["Punk Night"])
        self.assertNotContains(response, "Closed Show")

    def test_filter_by_category_keeps_city(self):
        response = self.client.get(reverse("events:event_list"), {"category": "exhibition", "city": "berlin"})
        self.assertContains(response, "Farbe als Raum")
        self.assertNotContains(response, "Punk Night")
        chip = next(c for c in response.context["category_chips"] if c["label"] == "Music")
        self.assertEqual(chip["href"], "?city=berlin&category=music")

    def test_week_lists_running_things_once(self):
        response = self.client.get(reverse("events:city_week", args=["berlin"]))
        self.assertEqual([e.title for e in response.context["running"]], ["Farbe als Raum"])
        self.assertContains(response, "All week")
        self.assertContains(response, "Farbe als Raum", count=1)
        self.assertContains(response, "Punk Night")
        self.assertNotContains(response, "Closed Show")
        response = self.client.get(reverse("events:city_week", args=["berlin"]), {"category": "music"})
        self.assertNotContains(response, "Farbe als Raum")

    def test_running_exhibition_can_be_saved_and_logged(self):
        self.client.force_login(User.objects.create_user("fan@example.com", "pw"))
        response = self.client.get(self.running.get_absolute_url())
        self.assertContains(response, "I was there")
        self.assertContains(response, ">Save<")
        self.assertContains(response, "Exhibition")

    def test_end_before_start_is_refused(self):
        owner = User.objects.create_user("owner@example.com", "pw")
        venue = self.running.venue
        venue.memberships.create(user=owner, role=Membership.OWNER)
        self.client.force_login(owner)
        response = self.client.post(
            reverse("events:create_event", args=["venue", venue.pk]),
            {
                "title": "Backwards",
                "category": self.exhibition.pk,
                "starts_at": "2030-10-02T10:00",
                "ends_at": "2030-09-01T18:00",
            },
        )
        self.assertContains(response, "can&#x27;t be before the start")
        self.assertFalse(Event.objects.filter(title="Backwards").exists())

    def test_submit_running_exhibition(self):
        """An exhibition that already opened can be submitted, as long as it hasn't closed."""
        self.client.force_login(User.objects.create_user("curator@example.com", "pw"))
        data = {
            "title": "Late Addition",
            "category": self.exhibition.pk,
            "venue": self.running.venue.pk,
            "starts_at": "2020-01-01T10:00",
            "ends_at": "2030-01-01T18:00",
            "relation": "Curator",
        }
        self.assertRedirects(self.client.post(reverse("events:submit_event"), data), reverse("accounts:dashboard"))
        submission = EventSubmission.objects.get()
        self.assertEqual(submission.approve().category, self.exhibition)

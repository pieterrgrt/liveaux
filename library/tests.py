import json
from datetime import date, timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Category, City, Event, Venue
from logbook.models import LogEntry

from . import ical, providers, services, stats
from .models import Copy, Entry, Episode, Item, ListItem, MediaList, MediaType, Play, Source, Status

FILM = {
    "title": "Past Lives",
    "original_title": "",
    "year": 2023,
    "release_date": date(2023, 6, 2),
    "creator": "Celine Song",
    "description": "Two childhood friends.",
    "genres": ["Drama", "Romance"],
    "runtime": 106,
    "total": 1,
    "status_text": "Released",
    "url": "https://www.themoviedb.org/movie/666277",
    "cover_url": "",
}


def series(next_air=None):
    today = timezone.localdate()
    return {
        "title": "Slow Horses",
        "year": 2022,
        "release_date": next_air,
        "creator": "Will Smith",
        "genres": ["Drama"],
        "runtime": 50,
        "total": 3,
        "status_text": "Returning Series" if next_air else "Ended",
        "url": "",
        "cover_url": "",
        "episodes": [
            {"season": 1, "number": 1, "title": "Failure's Contagious", "air_date": today - timedelta(days=30), "runtime": 50},
            {"season": 1, "number": 2, "title": "Work Drinks", "air_date": today - timedelta(days=23), "runtime": 48},
            {"season": 2, "number": 1, "title": "Last Stop", "air_date": next_air or today - timedelta(days=2), "runtime": 52},
        ],
    }


class LibraryTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("fan@example.com", "pw", display_name="Pieter")
        cls.other = User.objects.create_user("other@example.com", "pw")

    def setUp(self):
        self.client.force_login(self.user)

    def film(self):
        with mock.patch.object(providers, "fetch", return_value=dict(FILM)):
            return services.get_or_create_item(Source.TMDB, MediaType.MOVIE, "666277")

    def show(self, next_air=None):
        with mock.patch.object(providers, "fetch", return_value=series(next_air)):
            return services.get_or_create_item(Source.TMDB, MediaType.TV, "1")


class AddAndCheckInTests(LibraryTestCase):
    @override_settings(TMDB_API_KEY="key")
    def test_search_and_add(self):
        result = {
            "source": "tmdb",
            "source_id": "666277",
            "media_type": "movie",
            "title": "Past Lives",
            "year": 2023,
            "creator": "",
            "cover_url": "https://image.tmdb.org/t/p/w342/x.jpg",
        }
        fake_search = mock.Mock(return_value=[result])
        with mock.patch.dict(providers.PROVIDERS, {Source.TMDB: (fake_search, providers.tmdb_fetch)}):
            response = self.client.get(reverse("library:search"), {"type": "movie", "q": "past lives"})
        self.assertContains(response, "Past Lives")
        # The cover goes through liveaux, not straight to TMDB.
        self.assertNotContains(response, "image.tmdb.org")
        self.assertContains(response, reverse("library:cover_proxy"))

        with mock.patch.object(providers, "fetch", return_value=dict(FILM)), mock.patch.object(
            providers, "fetch_cover", side_effect=providers.ProviderError
        ):
            response = self.client.post(
                reverse("library:add"), {"source": "tmdb", "media_type": "movie", "source_id": "666277"}
            )
        item = Item.objects.get()
        self.assertRedirects(response, item.get_absolute_url())
        self.assertEqual(Entry.objects.get(user=self.user).status, Status.PLANNING)
        self.assertContains(self.client.get(item.get_absolute_url()), "Celine Song")

    def test_without_key_films_are_added_by_hand(self):
        response = self.client.get(reverse("library:search"), {"type": "movie", "q": "x"})
        self.assertContains(response, "Add by hand")
        response = self.client.post(
            reverse("library:add_manual"),
            {"media_type": "comic", "title": "Saga", "year": "2012", "total": "54", "genres": "Fantasy, Space"},
        )
        item = Item.objects.get(title="Saga")
        self.assertRedirects(response, item.get_absolute_url())
        self.assertEqual(item.genres, ["Fantasy", "Space"])
        self.assertEqual(item.created_by, self.user)

    def test_manual_items_are_private(self):
        item = Item.objects.create(media_type=MediaType.BOOK, title="My diary", created_by=self.other)
        self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)

    def test_watching_a_film(self):
        item = self.film()
        self.client.post(reverse("library:check_in", args=[item.pk]))
        entry = Entry.objects.get(user=self.user, item=item)
        self.assertEqual((entry.status, entry.progress, entry.finished_on), (Status.COMPLETED, 1, timezone.localdate()))
        self.assertEqual(Play.objects.get().minutes, 106)
        # Watching it again counts as a rewatch.
        self.client.post(reverse("library:check_in", args=[item.pk]), {"minutes": "100", "note": "Still great"})
        entry.refresh_from_db()
        self.assertEqual(entry.repeats, 1)
        self.assertEqual(Play.objects.first().note, "Still great")
        # Undo takes the rewatch back.
        self.client.post(reverse("library:play_delete", args=[Play.objects.first().pk]))
        entry.refresh_from_db()
        self.assertEqual(entry.repeats, 0)

    def test_check_in_in_the_future_is_refused(self):
        item = self.film()
        later = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        self.client.post(reverse("library:check_in", args=[item.pk]), {"played_at": later})
        self.assertFalse(Play.objects.exists())

    def test_episodes_and_up_next(self):
        item = self.show()
        self.assertEqual(item.episodes.count(), 3)
        first = item.episodes.get(season=1, number=1)
        self.client.post(reverse("library:check_in", args=[item.pk]), {"episode": first.pk})
        entry = Entry.objects.get(user=self.user, item=item)
        self.assertEqual((entry.status, entry.progress), (Status.IN_PROGRESS, 1))

        row = services.up_next(self.user)[0]
        self.assertEqual(row["episode"].code, "S01E02")
        self.assertEqual(row["left"], 2)
        self.assertContains(self.client.get(reverse("home")), "S01E02")

        self.client.post(reverse("library:check_in_season", args=[item.pk, 1]))
        self.client.post(reverse("library:check_in_season", args=[item.pk, 2]))
        entry.refresh_from_db()
        self.assertEqual((entry.progress, entry.status), (3, Status.COMPLETED))  # ended, all seen
        self.assertEqual(services.up_next(self.user), [])

    def test_running_series_is_not_completed_when_caught_up(self):
        item = self.show(next_air=timezone.localdate() + timedelta(days=5))
        services.check_in_season(self.user, item, 1)
        self.assertEqual(Entry.objects.get(item=item).status, Status.IN_PROGRESS)

    def test_sessions_and_episodic(self):
        game = Item.objects.create(media_type=MediaType.GAME, title="Hades", created_by=self.user)
        services.check_in(self.user, game, minutes=90)
        services.check_in(self.user, game, minutes=30)
        entry = Entry.objects.get(item=game)
        self.assertEqual((entry.status, entry.progress), (Status.IN_PROGRESS, 2))
        manga = Item.objects.create(media_type=MediaType.MANGA, title="Mushishi", total=2, created_by=self.user)
        services.check_in(self.user, manga)
        services.check_in(self.user, manga)
        self.assertEqual(Entry.objects.get(item=manga).status, Status.COMPLETED)

    def test_entry_form(self):
        item = self.film()
        response = self.client.post(
            reverse("library:entry_update", args=[item.pk]),
            {"status": "completed", "score": "9", "progress": "1", "repeats": "0", "notes": "Wow"},
        )
        self.assertRedirects(response, item.get_absolute_url())
        entry = Entry.objects.get(user=self.user, item=item)
        self.assertEqual((entry.score, entry.notes, entry.finished_on), (9, "Wow", timezone.localdate()))
        self.client.post(reverse("library:entry_update", args=[item.pk]), {"status": "completed", "score": "11", "repeats": "0", "progress": "1"})
        entry.refresh_from_db()
        self.assertEqual(entry.score, 9)

    def test_remove_from_library(self):
        item = self.film()
        services.check_in(self.user, item)
        services.check_in(self.other, item)
        self.client.post(reverse("library:entry_remove", args=[item.pk]))
        self.assertFalse(Entry.objects.filter(user=self.user).exists())
        self.assertFalse(Play.objects.filter(user=self.user).exists())
        self.assertTrue(Play.objects.filter(user=self.other).exists())

    def test_link_manual_item_to_source(self):
        manual = Item.objects.create(media_type=MediaType.MOVIE, title="past lives", year=2023, created_by=self.user)
        services.check_in(self.user, manual)
        lst = MediaList.objects.create(user=self.user, name="Faves")
        ListItem.objects.create(media_list=lst, item=manual)
        with override_settings(TMDB_API_KEY="key"), mock.patch.object(providers, "fetch", return_value=dict(FILM)):
            response = self.client.post(reverse("library:link", args=[manual.pk]), {"source_id": "666277"})
        item = Item.objects.get(source=Source.TMDB)
        self.assertRedirects(response, item.get_absolute_url())
        self.assertFalse(Item.objects.filter(pk=manual.pk).exists())
        self.assertEqual(Entry.objects.get(user=self.user).item, item)
        self.assertEqual(Play.objects.get().item, item)
        self.assertEqual(lst.get_items(), [item])

    def test_open_redirect_is_blocked(self):
        item = self.film()
        response = self.client.post(reverse("library:check_in", args=[item.pk]), {"next": "//evil.example/"})
        self.assertRedirects(response, item.get_absolute_url())


class ListAndCollectionTests(LibraryTestCase):
    def test_lists(self):
        item = self.film()
        self.client.post(reverse("library:list_create"), {"name": "Comfort films", "is_public": "on"})
        lst = MediaList.objects.get()
        self.client.post(reverse("library:list_toggle_item", args=[lst.pk, item.pk]))
        self.assertEqual(lst.get_items(), [item])

        self.client.logout()
        response = self.client.get(lst.get_absolute_url())
        self.assertContains(response, "Past Lives")
        feed = self.client.get(reverse("library:list_feed", args=[lst.pk]))
        self.assertContains(feed, "<title>Past Lives (2023)</title>")

        lst.is_public = False
        lst.save()
        self.assertEqual(self.client.get(lst.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(reverse("library:list_feed", args=[lst.pk])).status_code, 404)

    def test_smart_list(self):
        good = self.film()
        Entry.objects.create(user=self.user, item=good, status=Status.COMPLETED, score=9)
        meh = Item.objects.create(media_type=MediaType.MOVIE, title="Meh", genres=["Drama"], created_by=self.user)
        Entry.objects.create(user=self.user, item=meh, status=Status.COMPLETED, score=4)
        self.client.post(
            reverse("library:list_create"),
            {"name": "Best drama", "is_smart": "on", "min_score": "8", "genre": "drama", "media_type": "movie"},
        )
        lst = MediaList.objects.get()
        self.assertEqual(lst.rules, {"media_type": "movie", "min_score": 8, "genre": "drama"})
        self.assertEqual(lst.get_items(), [good])

    def test_collection(self):
        item = self.film()
        self.client.post(reverse("library:copy_add", args=[item.pk]), {"format": "bluray", "resolution": "1080p"})
        copy = Copy.objects.get()
        self.assertContains(self.client.get(reverse("library:collection")), "Blu-ray")
        self.client.force_login(self.other)
        self.client.post(reverse("library:copy_delete", args=[copy.pk]))
        self.assertTrue(Copy.objects.exists())


class CalendarAndStatsTests(LibraryTestCase):
    def test_calendar_has_episodes_releases_and_events(self):
        today = timezone.localdate()
        item = self.show(next_air=today + timedelta(days=3))
        services.track(self.user, item)
        Item.objects.create(media_type=MediaType.GAME, title="Hollow Knight: Silksong", release_date=today + timedelta(days=5), created_by=self.user)
        services.track(self.user, Item.objects.get(title__startswith="Hollow"))
        city = City.objects.create(name="Berlin", slug="berlin")
        event = Event.objects.create(
            category=Category.objects.get(slug="music"),
            title="Big Thief",
            venue=Venue.objects.create(name="Columbiahalle", city=city),
            starts_at=timezone.now() + timedelta(days=2),
        )
        event.saved_by.add(self.user)

        days = services.calendar(self.user, today, today + timedelta(days=14))
        titles = [row["title"] for _, rows in days for row in rows]
        self.assertEqual(titles, ["Big Thief", "Slow Horses", "Hollow Knight: Silksong"])

        response = self.client.get(reverse("library:calendar"))
        self.assertContains(response, "S02E01")
        feed = self.client.get(reverse("library:calendar_ics", args=[self.user.get_api_token()]))
        self.assertEqual(feed["Content-Type"], "text/calendar; charset=utf-8")
        body = feed.content.decode()
        self.assertIn("SUMMARY:Big Thief", body)
        self.assertIn("SUMMARY:Hollow Knight: Silksong", body)
        self.assertEqual(self.client.get(reverse("library:calendar_ics", args=["x" * 40])).status_code, 404)

    def test_ical_folds_long_lines(self):
        text = ical.render([(date(2026, 1, 1), [{"uid": "a", "title": "x" * 200, "label": "Out", "detail": "", "url": "/"}])], "liveaux.eu")
        self.assertTrue(all(len(line.encode()) <= 75 for line in text.split("\r\n")))

    def test_streaks(self):
        today = timezone.localdate()
        days = {today, today - timedelta(days=1), today - timedelta(days=2), today - timedelta(days=10), today - timedelta(days=11)}
        self.assertEqual(stats.streaks(days), (3, 3))
        self.assertEqual(stats.streaks({today - timedelta(days=1)}), (1, 1))
        self.assertEqual(stats.streaks(set()), (0, 0))

    def test_stats_page(self):
        item = self.film()
        services.check_in(self.user, item)
        Entry.objects.filter(item=item).update(score=9)
        city = City.objects.create(name="Berlin", slug="berlin")
        event = Event.objects.create(
            category=Category.objects.get(slug="music"),
            title="Punk",
            venue=Venue.objects.create(name="SO36", city=city),
            starts_at=timezone.now() - timedelta(hours=1),
        )
        LogEntry.objects.create(user=self.user, event=event)
        data = stats.compute(self.user)
        self.assertEqual((data["play_count"], data["events"], data["hours"]), (1, 1, 1.8))
        self.assertEqual(data["by_type"][0]["label"], "Films")
        response = self.client.get(reverse("library:stats"))
        self.assertContains(response, "Celine Song")
        self.assertContains(self.client.get(reverse("library:diary")), "Punk")


class ImportExportTests(LibraryTestCase):
    def upload(self, text, name="data.csv"):
        return self.client.post(reverse("library:import"), {"file": SimpleUploadedFile(name, text.encode())})

    def test_letterboxd(self):
        self.film()
        response = self.upload(
            "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n"
            "2026-01-03,Past Lives,2023,https://boxd.it/x,4.5,,,2026-01-02\n"
            "2026-02-01,Aftersun,2022,https://boxd.it/y,5,,,2026-02-01\n"
        )
        self.assertRedirects(response, reverse("library:index"))
        known = Entry.objects.get(item__source=Source.TMDB)
        self.assertEqual((known.score, known.status), (9, Status.COMPLETED))
        self.assertEqual(Entry.objects.get(item__title="Aftersun").item.source, Source.MANUAL)
        self.assertEqual(Play.objects.count(), 2)
        # Importing again adds nothing.
        self.upload("Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n2026-02-01,Aftersun,2022,u,5,,,2026-02-01\n")
        self.assertEqual((Item.objects.count(), Play.objects.count()), (2, 2))

    def test_goodreads_and_imdb(self):
        self.upload(
            "Book Id,Title,Author,My Rating,Number of Pages,Original Publication Year,Date Read,Exclusive Shelf,My Review\n"
            "1,Piranesi,Susanna Clarke,5,272,2020,2026/03/01,read,\n"
            "2,Middlemarch,George Eliot,0,880,1871,,to-read,\n"
        )
        self.assertEqual(Entry.objects.get(item__title="Piranesi").progress, 272)
        self.assertEqual(Entry.objects.get(item__title="Middlemarch").status, Status.PLANNING)
        self.upload(
            "Const,Your Rating,Date Rated,Title,URL,Title Type,IMDb Rating,Runtime (mins),Year,Genres,Num Votes,Release Date,Directors\n"
            "tt1,8,2025-05-05,Severance,u,TV Series,8.7,55,2022,Drama,1,2022-02-18,\n"
        )
        entry = Entry.objects.get(item__title="Severance")
        self.assertEqual((entry.item.media_type, entry.score), (MediaType.TV, 8))

    def test_unknown_file(self):
        response = self.upload("a,b\n1,2\n")
        self.assertContains(response, "recognise this file")

    def test_export_round_trip(self):
        item = self.film()
        Entry.objects.create(user=self.user, item=item, status=Status.COMPLETED, score=8, notes="Yes")
        csv_text = self.client.get(reverse("library:export_csv")).content.decode()
        self.assertIn("Past Lives", csv_text)
        self.client.force_login(self.other)
        self.upload(csv_text)
        entry = Entry.objects.get(user=self.other)
        self.assertEqual((entry.item, entry.score, entry.notes), (item, 8, "Yes"))

    def test_account_export_includes_library(self):
        services.check_in(self.user, self.film())
        data = self.client.get(reverse("accounts:export")).json()
        self.assertEqual(data["library"][0]["title"], "Past Lives")
        self.assertEqual(len(data["check_ins"]), 1)


class ConnectTests(LibraryTestCase):
    def test_plex_webhook(self):
        item = self.film()
        payload = {
            "event": "media.scrobble",
            "Metadata": {"type": "movie", "title": "Past Lives", "year": 2023, "Guid": [{"id": "tmdb://666277"}]},
        }
        self.client.logout()
        url = reverse("library:webhook", args=[self.user.get_api_token(), "plex"])
        response = self.client.post(url, {"payload": json.dumps(payload)})
        self.assertEqual(response.json()["logged"], True)
        play = Play.objects.get()
        self.assertEqual((play.item, play.via), (item, Play.Via.PLEX))
        # Pausing isn't watching.
        self.client.post(url, {"payload": json.dumps(dict(payload, event="media.pause"))})
        self.assertEqual(Play.objects.count(), 1)
        self.assertEqual(self.client.post(reverse("library:webhook", args=["n" * 40, "plex"])).status_code, 404)

    def test_jellyfin_episode(self):
        item = self.show()
        services.track(self.user, item)
        payload = {
            "NotificationType": "PlaybackStop",
            "PlayedToCompletion": True,
            "ItemType": "Episode",
            "SeriesName": "slow horses",
            "SeasonNumber": 1,
            "EpisodeNumber": 2,
        }
        url = reverse("library:webhook", args=[self.user.get_api_token(), "jellyfin"])
        self.client.post(url, json.dumps(payload), content_type="application/json")
        self.assertEqual(Play.objects.get().episode, item.episodes.get(season=1, number=2))

    def test_api(self):
        item = self.film()
        auth = {"HTTP_AUTHORIZATION": f"Bearer {self.user.get_api_token()}"}
        self.client.logout()
        self.assertEqual(self.client.get(reverse("library:api_entries")).status_code, 401)
        response = self.client.post(
            reverse("library:api_plays"), json.dumps({"item": item.pk, "minutes": 100}), content_type="application/json", **auth
        )
        self.assertEqual(response.status_code, 201)
        entries = self.client.get(reverse("library:api_entries"), **auth).json()["entries"]
        self.assertEqual(entries[0]["status"], "completed")
        plays = self.client.get(reverse("library:api_plays"), **auth).json()["plays"]
        self.assertEqual(plays[0]["minutes"], 100)

    def test_reset_token(self):
        old = self.user.get_api_token()
        self.client.post(reverse("library:reset_token"))
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.api_token, old)
        self.assertEqual(self.client.get(reverse("library:calendar_ics", args=[old])).status_code, 404)


class PagesTests(LibraryTestCase):
    def test_every_page_renders(self):
        item = self.show()
        services.check_in(self.user, item, episode=item.episodes.first())
        film = self.film()
        services.check_in(self.user, film)
        lst = MediaList.objects.create(user=self.user, name="L", is_public=True)
        for name, args in [
            ("home", []),
            ("library:index", []),
            ("library:browse", []),
            ("library:search", []),
            ("library:add_manual", []),
            ("library:item", [item.pk]),
            ("library:item", [film.pk]),
            ("library:calendar", []),
            ("library:stats", []),
            ("library:discover", []),
            ("library:diary", []),
            ("library:collection", []),
            ("library:import", []),
            ("library:connect", []),
            ("library:lists", []),
            ("library:list_create", []),
            ("library:list_detail", [lst.pk]),
            ("library:list_edit", [lst.pk]),
            ("accounts:dashboard", []),
            ("accounts:settings", []),
        ]:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_home_for_visitors(self):
        self.client.logout()
        response = self.client.get(reverse("home"))
        self.assertContains(response, "At home")
        self.assertContains(self.client.get(reverse("aux")), "Your library")
        self.assertEqual(self.client.get(reverse("library:index")).status_code, 302)

    def test_public_library(self):
        Entry.objects.create(user=self.user, item=self.film(), status=Status.COMPLETED, score=9)
        url = reverse("library:public", args=[self.user.pk])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 404)
        self.user.library_is_public = True
        self.user.save()
        response = self.client.get(url)
        self.assertContains(response, "Past Lives")
        self.assertNotContains(response, "fan@example.com")

    def test_cover_proxy_only_serves_signed_known_hosts(self):
        self.assertFalse(providers.cover_allowed("https://evil.example/x.jpg"))
        self.assertFalse(providers.cover_allowed("http://image.tmdb.org/x.jpg"))
        self.assertTrue(providers.cover_allowed("https://is3-ssl.mzstatic.com/x.jpg"))
        response = self.client.get(reverse("library:cover_proxy"), {"u": "https://evil.example/x.jpg"})
        self.assertEqual(response.status_code, 404)

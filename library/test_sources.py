"""Every source with its HTTP answers mocked: search, details, and the scores under Elsewhere."""

from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import User

from . import providers, ratings, services
from .models import Entry, ExternalRating, Item, MediaType, Source, Status


class FakeWeb:
    """Stands in for providers._get_json: answers by the first route whose text is in the URL (or query)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, *, params=None, headers=None, data=None, timeout=None):
        self.calls.append((url, params or {}, data))
        haystack = url + " " + " ".join(str(v) for v in (params or {}).values()) + " " + (data or b"").decode()
        for needle, answer in self.routes:
            if needle in haystack:
                if isinstance(answer, Exception):
                    raise answer
                return answer(url, params or {}) if callable(answer) else answer
        raise AssertionError(f"Unexpected request: {url} {params}")


class SourceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        guard = mock.patch("urllib.request.urlopen", side_effect=AssertionError("No network in tests"))
        guard.start()
        self.addCleanup(guard.stop)
        sleep = mock.patch.object(providers.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def web(self, *routes):
        fake = FakeWeb(list(routes))
        patcher = mock.patch.object(providers, "_get_json", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


# TVmaze

TVMAZE_SEARCH = [
    {
        "score": 0.9,
        "show": {
            "id": 44933,
            "name": "Severance",
            "premiered": "2022-02-18",
            "network": None,
            "webChannel": {"name": "Apple TV"},
            "image": {"medium": "https://static.tvmaze.com/m.jpg", "original": "https://static.tvmaze.com/o.jpg"},
        },
    }
]
TVMAZE_SHOW = {
    "id": 44933,
    "url": "https://www.tvmaze.com/shows/44933/severance",
    "name": "Severance",
    "genres": ["Drama", "Science-Fiction"],
    "status": "Running",
    "runtime": None,
    "averageRuntime": 49,
    "premiered": "2022-02-18",
    "rating": {"average": 8.4},
    "image": {"medium": "https://static.tvmaze.com/m.jpg", "original": "https://static.tvmaze.com/o.jpg"},
    "summary": "<p>Mark leads a team at <b>Lumon</b> &amp; more.</p>",
    "_embedded": {
        "episodes": [
            {"season": 1, "number": 1, "name": "Good News About Hell", "airdate": "2022-02-18", "runtime": 57, "type": "regular"},
            {"season": 1, "number": 2, "name": "Half Loop", "airdate": "2022-02-18", "runtime": 53, "type": "regular"},
            {"season": 1, "number": None, "name": "Behind the scenes", "airdate": "2022-03-01", "runtime": 10, "type": "significant_special"},
            {"season": 3, "number": 1, "name": "", "airdate": "2027-01-15", "runtime": None, "type": "regular"},
        ],
        "crew": [
            {"type": "Creator", "person": {"name": "Dan Erickson"}},
            {"type": "Executive Producer", "person": {"name": "Ben Stiller"}},
        ],
        "nextepisode": {"airdate": "2027-01-15"},
    },
}


class TVmazeTests(SourceTestCase):
    def test_search(self):
        self.web(("/search/shows", TVMAZE_SEARCH))
        [result] = providers.tvmaze_search(MediaType.TV, "severance")
        self.assertEqual(result["source"], Source.TVMAZE)
        self.assertEqual(result["source_id"], "44933")
        self.assertEqual((result["title"], result["year"], result["creator"]), ("Severance", 2022, "Apple TV"))
        self.assertTrue(providers.cover_allowed(result["cover_url"]))

    def test_fetch_has_episodes_and_next_episode(self):
        self.web(("/shows/44933", TVMAZE_SHOW))
        data = providers.tvmaze_fetch(MediaType.TV, "44933")
        self.assertEqual(data["creator"], "Dan Erickson")
        self.assertEqual(data["description"], "Mark leads a team at Lumon & more.")
        self.assertEqual(data["runtime"], 49)
        self.assertEqual(data["release_date"], date(2027, 1, 15))
        self.assertEqual(data["status_text"], "Running")
        self.assertEqual(len(data["episodes"]), 3)  # the special without a number is left out
        self.assertEqual(data["episodes"][0], {"season": 1, "number": 1, "title": "Good News About Hell", "air_date": date(2022, 2, 18), "runtime": 57})
        self.assertEqual(data["total"], 3)

    def test_running_show_is_not_finished_when_caught_up(self):
        self.web(("/shows/44933", TVMAZE_SHOW))
        user = User.objects.create_user("fan@example.com", "pw")
        with mock.patch.object(providers, "fetch_cover", side_effect=providers.ProviderError):
            item = services.get_or_create_item(Source.TVMAZE, MediaType.TV, "44933")
        self.assertEqual(item.episodes.count(), 3)
        services.check_in_season(user, item, 1)
        self.assertEqual(Entry.objects.get(user=user).status, Status.IN_PROGRESS)


# Wikidata and Wikipedia: films and games

WD_PERFECT_DAYS = {
    "id": "Q117663112",
    "labels": {"en": {"value": "Perfect Days"}},
    "sitelinks": {"enwiki": {"title": "Perfect Days"}},
    "claims": {
        "P577": [
            {"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+2023-09-01T00:00:00Z", "precision": 11}}}},
            {"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+2023-05-25T00:00:00Z", "precision": 11}}}},
        ],
        "P57": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q55411"}}}}],
        "P136": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q130232"}}}}],
        "P2047": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"amount": "+123", "unit": "http://www.wikidata.org/entity/Q7727"}}}}],
        "P1476": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"text": "Perfect Days", "language": "en"}}}}],
        "P4947": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "976893"}}}],
        "P345": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "tt27503384"}}}],
        "P1258": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "m/perfect_days_2023"}}}],
        "P1712": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "movie/perfect-days"}}}],
        "P444": [
            {
                "rank": "normal",
                "mainsnak": {"datavalue": {"value": "93%"}},
                "qualifiers": {
                    "P447": [{"datavalue": {"value": {"id": "Q105584"}}}],
                    "P459": [{"datavalue": {"value": {"id": "Q108403393"}}}],
                    "P585": [{"datavalue": {"value": {"time": "+2024-01-01T00:00:00Z", "precision": 11}}}],
                },
            },
            {
                "rank": "normal",
                "mainsnak": {"datavalue": {"value": "96%"}},
                "qualifiers": {
                    "P447": [{"datavalue": {"value": {"id": "Q105584"}}}],
                    "P459": [{"datavalue": {"value": {"id": "Q108403393"}}}],
                    "P585": [{"datavalue": {"value": {"time": "+2024-09-02T00:00:00Z", "precision": 11}}}],
                    "P7887": [{"datavalue": {"value": {"amount": "+184", "unit": "http://www.wikidata.org/entity/Q80698083"}}}],
                },
            },
            {
                "rank": "normal",
                "mainsnak": {"datavalue": {"value": "80/100"}},
                "qualifiers": {
                    "P447": [{"datavalue": {"value": {"id": "Q150248"}}}],
                    "P459": [{"datavalue": {"value": {"id": "Q106515043"}}}],
                    "P7887": [{"datavalue": {"value": {"amount": "+38", "unit": "http://www.wikidata.org/entity/Q80698083"}}}],
                },
            },
            {
                "rank": "deprecated",
                "mainsnak": {"datavalue": {"value": "1/10"}},
                "qualifiers": {"P447": [{"datavalue": {"value": {"id": "Q37312"}}}]},
            },
        ],
    },
}
WD_LABELS = {
    "Q55411": "Wim Wenders",
    "Q130232": "drama film",
    "Q105584": "Rotten Tomatoes",
    "Q150248": "Metacritic",
    "Q108403393": "Tomatometer score",
    "Q106515043": "Metascore",
    "Q69427151": "Mobius Digital",
    "Q343568": "action-adventure game",
}
WD_OUTER_WILDS = {
    "id": "Q19631660",
    "labels": {"mul": {"value": "Outer Wilds"}},
    "sitelinks": {},
    "claims": {
        "P577": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"time": "+2019-00-00T00:00:00Z", "precision": 9}}}}],
        "P178": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q69427151"}}}}],
        "P136": [{"rank": "normal", "mainsnak": {"datavalue": {"value": {"id": "Q343568"}}}}],
        "P18": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "Outer Wilds logo.png"}}}],
    },
}


def wikidata_api(entities):
    def answer(url, params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": qid} for qid in entities]}}
        ids = params["ids"].split("|")
        if params.get("props") == "labels":
            return {"entities": {i: {"id": i, "labels": {"en": {"value": WD_LABELS.get(i, i)}}} for i in ids}}
        return {"entities": {i: entities[i] for i in ids if i in entities}}

    return answer


WIKIPEDIA_PAGE = {
    "query": {
        "pages": [
            {
                "title": "Perfect Days",
                "fullurl": "https://en.wikipedia.org/wiki/Perfect_Days",
                "thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/en/c/c9/Perfect_Days_poster.jpg?utm_source=x"},
                "extract": "Perfect Days is a 2023 drama film directed by Wim Wenders.",
            }
        ]
    }
}


class WikidataTests(SourceTestCase):
    def test_film_search(self):
        web = self.web(("wikidata.org", wikidata_api({"Q117663112": WD_PERFECT_DAYS})), ("wikipedia.org", WIKIPEDIA_PAGE))
        [result] = providers.wikidata_search(MediaType.MOVIE, "perfect days")
        self.assertEqual(result["source"], Source.WIKIDATA)
        self.assertEqual((result["title"], result["year"], result["creator"]), ("Perfect Days", 2023, "Wim Wenders"))
        self.assertEqual(result["cover_url"], "https://upload.wikimedia.org/wikipedia/en/c/c9/Perfect_Days_poster.jpg")
        self.assertTrue(providers.cover_allowed(result["cover_url"]))
        search = web.calls[0][1]["srsearch"]
        self.assertIn("haswbstatement:P31=Q11424|", search)

    def test_film_details(self):
        self.web(("wikidata.org", wikidata_api({"Q117663112": WD_PERFECT_DAYS})), ("wikipedia.org", WIKIPEDIA_PAGE))
        data = providers.wikidata_fetch(MediaType.MOVIE, "Q117663112")
        self.assertEqual(data["release_date"], date(2023, 5, 25))  # the earliest release
        self.assertEqual(data["runtime"], 123)
        self.assertEqual(data["genres"], ["Drama"])
        self.assertEqual(data["original_title"], "")
        self.assertIn("Wim Wenders", data["description"])
        self.assertIn("From Wikipedia (CC BY-SA 4.0)", data["description"])
        self.assertEqual(data["url"], "https://en.wikipedia.org/wiki/Perfect_Days")

    def test_game_without_wikipedia_page_uses_commons(self):
        self.web(("wikidata.org", wikidata_api({"Q19631660": WD_OUTER_WILDS})))
        [result] = providers.wikidata_search(MediaType.GAME, "outer wilds")
        self.assertEqual((result["title"], result["year"], result["creator"]), ("Outer Wilds", 2019, "Mobius Digital"))
        self.assertTrue(result["cover_url"].startswith("https://commons.wikimedia.org/wiki/Special:FilePath/Outer_Wilds_logo.png"))
        data = providers.wikidata_fetch(MediaType.GAME, "Q19631660")
        self.assertIsNone(data["release_date"])  # only the year is known
        self.assertEqual(data["genres"], ["Action-adventure"])
        self.assertEqual(data["url"], "https://www.wikidata.org/wiki/Q19631660")

    def test_exact_title_first(self):
        hades2 = {"id": "Q2", "labels": {"en": {"value": "Hades II"}}, "claims": {}, "sitelinks": {}}
        hades = {"id": "Q1", "labels": {"en": {"value": "Hades"}}, "claims": {}, "sitelinks": {}}
        self.web(("wikidata.org", wikidata_api({"Q2": hades2, "Q1": hades})))
        self.assertEqual([r["title"] for r in providers.wikidata_search(MediaType.GAME, "hades")], ["Hades", "Hades II"])

    def test_bad_id(self):
        with self.assertRaises(providers.ProviderError):
            providers.wikidata_fetch(MediaType.MOVIE, "1234")

    def test_keyless_sources(self):
        with override_settings(TMDB_API_KEY="", IGDB_CLIENT_ID="", IGDB_CLIENT_SECRET=""):
            self.assertEqual(providers.source_for(MediaType.MOVIE), Source.WIKIDATA)
            self.assertEqual(providers.source_for(MediaType.TV), Source.TVMAZE)
            self.assertEqual(providers.source_for(MediaType.GAME), Source.WIKIDATA)
        with override_settings(TMDB_API_KEY="k", IGDB_CLIENT_ID="i", IGDB_CLIENT_SECRET="s"):
            self.assertEqual(providers.source_for(MediaType.MOVIE), Source.TMDB)
            self.assertEqual(providers.source_for(MediaType.TV), Source.TMDB)
            self.assertEqual(providers.source_for(MediaType.GAME), Source.IGDB)
        self.assertIsNone(providers.source_for(MediaType.COMIC))


# The sources that were there before


class AniListTests(SourceTestCase):
    MEDIA = {
        "id": 154587,
        "siteUrl": "https://anilist.co/anime/154587",
        "title": {"romaji": "Sousou no Frieren", "english": "Frieren: Beyond Journey's End", "native": "葬送のフリーレン"},
        "startDate": {"year": 2023, "month": 9, "day": 29},
        "description": "The adventure is over.<br><br>(Source: Crunchyroll)&nbsp;<i>x</i>",
        "genres": ["Adventure"],
        "episodes": 28,
        "chapters": None,
        "duration": 24,
        "status": "FINISHED",
        "format": "TV",
        "coverImage": {"extraLarge": "https://s4.anilist.co/file/large.jpg", "large": "https://s4.anilist.co/file/medium.jpg"},
        "studios": {"nodes": [{"name": "MADHOUSE"}]},
        "staff": {"nodes": []},
        "nextAiringEpisode": None,
    }

    def test_search_and_fetch(self):
        self.web(("Page(perPage", {"data": {"Page": {"media": [self.MEDIA]}}}), ("Media(id", {"data": {"Media": self.MEDIA}}))
        [result] = providers.anilist_search(MediaType.ANIME, "frieren")
        self.assertEqual(result["cover_url"], "https://s4.anilist.co/file/large.jpg")  # the big one
        self.assertEqual(result["creator"], "MADHOUSE")
        data = providers.anilist_fetch(MediaType.ANIME, "154587")
        self.assertEqual(data["description"], "The adventure is over.\n\n(Source: Crunchyroll)\xa0x")
        self.assertEqual((data["total"], data["runtime"], data["status_text"]), (28, 24, "Finished"))
        self.assertEqual(data["original_title"], "葬送のフリーレン")

    def test_errors(self):
        self.web(("graphql", {"errors": [{"message": "Not Found."}], "data": None}))
        with self.assertRaisesMessage(providers.ProviderError, "Not Found."):
            providers.anilist_fetch(MediaType.ANIME, "1")


class OpenLibraryTests(SourceTestCase):
    DOC = {
        "key": "/works/OL46611W",
        "title": "Die Ringe des Saturn",
        "author_name": ["W. G. Sebald", "Michael Hulse", "W. G. Sebald"],
        "first_publish_year": 1995,
        "cover_i": 1,
        "number_of_pages_median": 296,
        "subject": ["Travel"],
        "editions": {"docs": [{"key": "/books/OL1M", "title": "The Rings of Saturn", "language": ["eng"], "cover_i": 2}]},
    }

    def test_english_title_and_cover(self):
        web = self.web(("search.json", {"docs": [self.DOC]}), ("/works/OL46611W.json", {"title": "Die Ringe des Saturn", "description": {"value": "A walk."}}))
        [result] = providers.openlibrary_search(MediaType.BOOK, "the rings of saturn")
        self.assertEqual(result["title"], "The Rings of Saturn")
        self.assertEqual(result["cover_url"], "https://covers.openlibrary.org/b/id/2-L.jpg")
        self.assertEqual(web.calls[0][1]["lang"], "en")
        data = providers.openlibrary_fetch(MediaType.BOOK, "OL46611W")
        self.assertEqual(data["title"], "The Rings of Saturn")
        self.assertEqual(data["original_title"], "Die Ringe des Saturn")
        self.assertEqual(data["creator"], "W. G. Sebald, Michael Hulse")
        self.assertEqual((data["description"], data["total"]), ("A walk.", 296))

    def test_no_english_edition(self):
        doc = dict(self.DOC, editions={"docs": [{"title": "Les Anneaux de Saturne", "language": ["fre"]}]})
        self.web(("search.json", {"docs": [doc]}))
        self.assertEqual(providers.openlibrary_search(MediaType.BOOK, "x")[0]["title"], "Die Ringe des Saturn")


class MusicBrainzTests(SourceTestCase):
    def group(self, gid, title, artist):
        return {"id": gid, "title": title, "first-release-date": "1971-06-22", "artist-credit": [{"name": artist}]}

    def test_artist_and_title_together_first(self):
        groups = [
            self.group("a", "Joni Mitchell's Blue", "Katie Noonan"),
            self.group("b", "Joni Mitchell", "Joni Mitchell"),
            self.group("c", "Blue", "Joni Mitchell"),
        ]
        self.web(("/release-group", {"release-groups": groups}))
        results = providers.musicbrainz_search(MediaType.MUSIC, "Joni Mitchell Blue")
        self.assertEqual([r["source_id"] for r in results], ["c", "a", "b"])

    def test_fetch(self):
        group = dict(self.group("c", "Blue", "Joni Mitchell"), genres=[{"name": "folk", "count": 3}], releases=[{"id": "r1"}])
        release = {"media": [{"tracks": [{"length": 180000}, {"length": 240000}]}]}
        self.web(("/release-group/c", group), ("/release/r1", release))
        data = providers.musicbrainz_fetch(MediaType.MUSIC, "c")
        self.assertEqual((data["total"], data["runtime"], data["release_date"]), (2, 7, date(1971, 6, 22)))

    def test_busy_once_then_fine(self):
        answers = [providers.ProviderError("HTTP Error 503"), {"release-groups": []}]

        def flaky(url, params):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.web(("/release-group", flaky))
        self.assertEqual(providers.musicbrainz_search(MediaType.MUSIC, "x"), [])


class ApplePodcastsTests(SourceTestCase):
    def test_search_and_fetch(self):
        podcast = {
            "collectionId": 1200361736,
            "collectionName": "The Daily",
            "artistName": "The New York Times",
            "releaseDate": "2026-10-27T09:00:00Z",
            "artworkUrl600": "https://is1-ssl.mzstatic.com/x/600x600bb.jpg",
            "genres": ["Daily News", "Podcasts"],
            "trackCount": 2761,
            "collectionViewUrl": "https://podcasts.apple.com/us/podcast/the-daily/id1200361736",
        }
        self.web(("/search", {"results": [podcast]}), ("/lookup", {"results": [podcast]}))
        [result] = providers.itunes_search(MediaType.PODCAST, "the daily")
        self.assertIsNone(result["year"])  # releaseDate is the newest episode
        data = providers.itunes_fetch(MediaType.PODCAST, "1200361736")
        self.assertEqual((data["total"], data["genres"]), (2761, ["Daily News"]))


class SearchCacheTests(SourceTestCase):
    def test_results_are_cached_per_source(self):
        web = self.web(("/search/shows", TVMAZE_SEARCH))
        providers.search(MediaType.TV, "Severance")
        providers.search(MediaType.TV, "severance ")
        self.assertEqual(len(web.calls), 1)


# Elsewhere


def wikidata_with_lookup(entities, lookup):
    """The Wikidata API, where a haswbstatement search for an id finds `lookup`."""
    api = wikidata_api(entities)

    def answer(url, params):
        if params.get("list") == "search":
            return {"query": {"search": [{"title": lookup}] if lookup else []}}
        return api(url, params)

    return answer


class ParseScoreTests(TestCase):
    def test_formats(self):
        self.assertEqual(ratings.parse_score("96%"), (96.0, 100.0))
        self.assertEqual(ratings.parse_score("80/100"), (80.0, 100.0))
        self.assertEqual(ratings.parse_score("7,8/10"), (7.8, 10.0))
        self.assertEqual(ratings.parse_score("4/5 stars"), (4.0, 5.0))
        self.assertEqual(ratings.parse_score("A-"), (None, None))


class ElsewhereTestCase(SourceTestCase):
    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user("fan@example.com", "pw")
        self.client.force_login(self.user)

    def item(self, source, media_type, source_id, **fields):
        return Item.objects.create(source=source, media_type=media_type, source_id=source_id, title="X", **fields)


class ElsewhereSourceTests(ElsewhereTestCase):
    def test_wikidata_scores_for_a_film(self):
        item = self.item(Source.WIKIDATA, MediaType.MOVIE, "Q117663112")
        self.web(("wikidata.org", wikidata_api({"Q117663112": WD_PERFECT_DAYS})))
        self.assertTrue(ratings.refresh(item))
        rt, meta = item.external_ratings.all()
        self.assertEqual((rt.label, rt.detail, rt.display, rt.value, rt.scale), ("Rotten Tomatoes", "Tomatometer score", "96%", 96, 100))
        self.assertEqual((rt.count, rt.count_label, rt.as_of), (184, "critic reviews", date(2024, 9, 2)))  # the newest one
        self.assertEqual(rt.url, "https://www.rottentomatoes.com/m/perfect_days_2023")
        self.assertEqual(rt.source, "Wikidata")
        self.assertEqual((meta.label, meta.display, meta.percent), ("Metacritic", "80/100", 80))
        self.assertEqual(meta.url, "https://www.metacritic.com/movie/perfect-days")
        self.assertFalse(item.external_ratings.filter(label="IMDb").exists())  # deprecated

    @override_settings(TMDB_API_KEY="key")
    def test_tmdb_through_wikidata(self):
        item = self.item(Source.TVMAZE, MediaType.TV, "44933")
        entity = {"id": "Q1", "claims": {"P4983": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "95396"}}}]}}
        web = self.web(
            ("wikidata.org", wikidata_with_lookup({"Q1": entity}, "Q1")),
            ("themoviedb.org/3/tv/95396", {"vote_average": 8.4, "vote_count": 2100}),
            ("/shows/44933", {"rating": {"average": 8.3}, "url": "https://www.tvmaze.com/shows/44933/severance"}),
        )
        ratings.refresh(item)
        self.assertIn("haswbstatement:P8600=44933", web.calls[0][1]["srsearch"])
        by_key = {r.key: r for r in item.external_ratings.all()}
        self.assertEqual((by_key["tmdb"].display, by_key["tmdb"].count, by_key["tmdb"].count_label), ("8.4/10", 2100, "votes"))
        self.assertEqual(by_key["tvmaze"].display, "8.3/10")

    def test_without_tmdb_key_no_tmdb(self):
        item = self.item(Source.TVMAZE, MediaType.TV, "44933")
        entity = {"id": "Q1", "claims": {"P4983": [{"rank": "normal", "mainsnak": {"datavalue": {"value": "95396"}}}]}}
        self.web(("wikidata.org", wikidata_with_lookup({"Q1": entity}, "Q1")), ("/shows/44933", {"rating": {"average": None}}))
        ratings.refresh(item)
        self.assertFalse(item.external_ratings.exists())

    def test_anilist(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "154587")
        self.web(
            ("wikidata.org", wikidata_with_lookup({}, "")),
            ("graphql", {"data": {"Media": {"siteUrl": "https://anilist.co/anime/154587", "averageScore": 91, "meanScore": 90, "popularity": 493490, "favourites": 1}}}),
        )
        ratings.refresh(item)
        row = item.external_ratings.get()
        self.assertEqual((row.display, row.count, row.count_label, row.percent), ("91%", 493490, "on lists", 91))

    def test_open_library_ratings_and_shelves(self):
        item = self.item(Source.OPENLIBRARY, MediaType.BOOK, "OL46611W")
        self.web(
            ("wikidata.org", wikidata_with_lookup({}, "")),
            ("ratings.json", {"summary": {"average": 4.0, "count": 1}}),
            ("bookshelves.json", {"counts": {"want_to_read": 11, "currently_reading": 1, "already_read": 1}}),
        )
        ratings.refresh(item)
        row = item.external_ratings.get()
        self.assertEqual((row.display, row.count, row.count_label), ("4/5", 1, "rating"))
        self.assertEqual(row.extra["shelves"]["want_to_read"], 11)
        response = self.client.get(item.get_absolute_url())
        self.assertContains(response, "11 want to read")

    def test_musicbrainz(self):
        item = self.item(Source.MUSICBRAINZ, MediaType.MUSIC, "42d725fb")
        self.web(
            ("wikidata.org", wikidata_with_lookup({}, "")),
            ("/release-group/42d725fb", {"rating": {"value": 4.2, "votes-count": 16}}),
        )
        ratings.refresh(item)
        row = item.external_ratings.get()
        self.assertEqual((row.display, row.count), ("4.2/5", 16))

    @override_settings(IGDB_CLIENT_ID="id", IGDB_CLIENT_SECRET="secret")
    def test_igdb(self):
        item = self.item(Source.IGDB, MediaType.GAME, "11737", url="https://www.igdb.com/games/outer-wilds")
        web = self.web(
            ("wikidata.org", wikidata_with_lookup({}, "")),
            ("oauth2/token", {"access_token": "t", "expires_in": 3600}),
            ("api.igdb.com", [{"url": "https://www.igdb.com/games/outer-wilds", "rating": 88.6, "rating_count": 900, "aggregated_rating": 85.2, "aggregated_rating_count": 40}]),
        )
        ratings.refresh(item)
        self.assertIn("haswbstatement:P5794=outer-wilds", web.calls[0][1]["srsearch"])
        self.assertEqual([r.display for r in item.external_ratings.all()], ["89%", "85%"])

    def test_failing_source_keeps_last_scores(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        ExternalRating.objects.create(item=item, key="anilist", source="AniList", label="AniList", display="80%")
        self.web(("wikidata.org", providers.ProviderError("down")), ("graphql", providers.ProviderError("down")))
        ratings.refresh(item, force=True)
        self.assertEqual(item.external_ratings.get().display, "80%")

    def test_score_gone_at_source_is_removed(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        ExternalRating.objects.create(item=item, key="anilist", source="AniList", label="AniList", display="80%")
        self.web(("wikidata.org", wikidata_with_lookup({}, "")), ("graphql", {"data": {"Media": {"averageScore": None}}}))
        ratings.refresh(item, force=True)
        self.assertFalse(item.external_ratings.exists())

    def test_only_when_stale(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        web = self.web(("wikidata.org", wikidata_with_lookup({}, "")), ("graphql", {"data": {"Media": {"averageScore": 70}}}))
        self.assertTrue(ratings.refresh(item))
        calls = len(web.calls)
        self.assertFalse(ratings.refresh(item))
        self.assertEqual(len(web.calls), calls)
        cache.clear()  # e.g. another worker: the stored rows still say it's fresh
        self.assertFalse(ratings.is_stale(item))
        ExternalRating.objects.update(fetched_at=timezone.now() - timedelta(hours=7))
        self.assertTrue(ratings.is_stale(item))

    def test_manual_items_are_never_fetched(self):
        item = Item.objects.create(media_type=MediaType.BOOK, title="Diary", created_by=self.user)
        self.assertFalse(ratings.refresh(item, force=True))


class ElsewherePageTests(ElsewhereTestCase):
    def test_item_page_shows_stored_scores_and_community_without_waiting(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        ExternalRating.objects.create(item=item, key="anilist", source="AniList", label="AniList", display="91%", value=91, scale=100, count=1200, count_label="on lists", url="https://anilist.co/anime/1")
        other = User.objects.create_user("other@example.com", "pw")
        Entry.objects.create(user=self.user, item=item, score=9)
        Entry.objects.create(user=other, item=item, score=8)
        web = self.web()  # any request would fail the test
        response = self.client.get(item.get_absolute_url())
        self.assertEqual(web.calls, [])
        self.assertContains(response, "Elsewhere")
        self.assertContains(response, "91%")
        self.assertContains(response, "1,200 on lists")
        self.assertContains(response, "8.5/10")  # liveaux: the average of 9 and 8
        self.assertContains(response, "2 scores")
        self.assertContains(response, "Updated")
        self.assertNotContains(response, "data-elsewhere=")  # fresh: no need to fetch again

    def test_stale_block_asks_the_script_to_fetch(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        self.web()
        response = self.client.get(item.get_absolute_url())
        url = reverse("library:elsewhere", args=[item.pk])
        self.assertContains(response, f'data-elsewhere="{url}"')
        self.assertContains(response, "Looking around")

    def test_fragment_fetches_and_renders(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        self.web(("wikidata.org", wikidata_with_lookup({}, "")), ("graphql", {"data": {"Media": {"averageScore": 77, "siteUrl": "https://anilist.co/anime/1"}}}))
        response = self.client.get(reverse("library:elsewhere", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, "77%")
        self.assertContains(response, 'href="https://anilist.co/anime/1"')
        self.assertNotContains(response, "data-elsewhere=")

    def test_fragment_never_breaks(self):
        item = self.item(Source.ANILIST, MediaType.ANIME, "1")
        with mock.patch.object(ratings, "collect", side_effect=RuntimeError("boom")):
            response = self.client.get(reverse("library:elsewhere", args=[item.pk]))
        self.assertEqual(response.status_code, 200)

    def test_fragment_needs_login_and_access(self):
        item = Item.objects.create(media_type=MediaType.BOOK, title="Private", created_by=User.objects.create_user("x@example.com", "pw"))
        self.assertEqual(self.client.get(reverse("library:elsewhere", args=[item.pk])).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("library:elsewhere", args=[item.pk])).status_code, 302)

    def test_refresh_library_fetches_scores_for_tracked_items(self):
        tracked = self.item(Source.ANILIST, MediaType.ANIME, "1", status_text="Finished")
        self.item(Source.ANILIST, MediaType.ANIME, "2", status_text="Finished")  # nobody tracks it
        Entry.objects.create(user=self.user, item=tracked, status=Status.COMPLETED)
        self.web(("wikidata.org", wikidata_with_lookup({}, "")), ("graphql", {"data": {"Media": {"averageScore": 70}}}))
        call_command("refresh_library", stdout=mock.Mock(), stderr=mock.Mock())
        self.assertEqual(ExternalRating.objects.get().item, tracked)


class WikimediaRetryTests(SourceTestCase):
    def test_busy_once_then_fine(self):
        answers = [providers.ProviderError("HTTP Error 503: Service Unavailable"), {"query": {"search": [{"title": "Q1"}]}}]

        def flaky(url, params):
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.web(("wikidata.org", flaky))
        self.assertEqual(providers.wikidata_find("x"), ["Q1"])

    def test_other_errors_are_not_retried(self):
        web = self.web(("wikidata.org", providers.ProviderError("HTTP Error 400")))
        with self.assertRaises(providers.ProviderError):
            providers.wikidata_find("x")
        self.assertEqual(len(web.calls), 1)


class WikipediaLeadTests(TestCase):
    def test_lead_is_short_enough_for_the_credit(self):
        long = "\n".join(["word " * 60, "more " * 60, "even " * 60])
        self.assertEqual(providers._lead(long).split(), ["word"] * 60)
        self.assertEqual(providers._lead("One.\nTwo."), "One.\n\nTwo.")

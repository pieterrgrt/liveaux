"""Where details about films, series, books and the rest come from.

Every provider turns its API into the same shape:

- `search(media_type, query)` returns a list of results:
  {"source", "source_id", "media_type", "title", "year", "creator", "cover_url"}
- `fetch(media_type, source_id)` returns the fields for an `Item`, plus "episodes" for series:
  [{"season", "number", "title", "air_date", "runtime"}]

All calls happen on the server, so visitors' browsers never talk to these services.
"""

import hashlib
import html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from django.conf import settings
from django.core.cache import cache

from .models import MediaType, Source

log = logging.getLogger(__name__)

USER_AGENT = "liveaux/1.0 (+https://liveaux.eu)"
TIMEOUT = 10


class ProviderError(Exception):
    """The source couldn't be reached or didn't understand us."""


def _request(url, *, params=None, headers=None, data=None, timeout=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout or TIMEOUT) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("Request to %s failed: %s", url.split("?")[0], error)
        raise ProviderError(str(error)) from error


def _get_json(url, *, params=None, headers=None, data=None, timeout=None):
    body = _request(url, params=params, headers=headers, data=data, timeout=timeout)
    try:
        return json.loads(body)
    except ValueError as error:
        raise ProviderError("The answer wasn't JSON.") from error


def _year(value):
    """The year from '2019-05-30', 2019, or None."""
    if not value:
        return None
    try:
        return int(str(value)[:4])
    except ValueError:
        return None


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


# TMDB: films and series. Needs TMDB_API_KEY (a v3 key or a v4 read access token).

TMDB = "https://api.themoviedb.org/3"
TMDB_IMAGES = "https://image.tmdb.org/t/p/w342"


def _tmdb(path, timeout=None, **params):
    key = settings.TMDB_API_KEY
    headers = {}
    if len(key) > 40:  # a v4 read access token
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    return _get_json(f"{TMDB}{path}", params=params, headers=headers, timeout=timeout)


def _tmdb_type(media_type):
    return "movie" if media_type == MediaType.MOVIE else "tv"


def tmdb_search(media_type, query):
    kind = _tmdb_type(media_type)
    data = _tmdb(f"/search/{kind}", query=query, include_adult="false")
    return [
        {
            "source": Source.TMDB,
            "source_id": str(r["id"]),
            "media_type": media_type,
            "title": r.get("title") or r.get("name") or "",
            "year": _year(r.get("release_date") or r.get("first_air_date")),
            "creator": "",
            "cover_url": f"{TMDB_IMAGES}{r['poster_path']}" if r.get("poster_path") else "",
        }
        for r in data.get("results", [])[:20]
    ]


def tmdb_fetch(media_type, source_id):
    kind = _tmdb_type(media_type)
    d = _tmdb(f"/{kind}/{source_id}", append_to_response="credits")
    fields = {
        "title": d.get("title") or d.get("name") or "",
        "original_title": d.get("original_title") or d.get("original_name") or "",
        "description": d.get("overview") or "",
        "genres": [g["name"] for g in d.get("genres", [])],
        "cover_url": f"{TMDB_IMAGES}{d['poster_path']}" if d.get("poster_path") else "",
        "status_text": d.get("status") or "",
        "url": f"https://www.themoviedb.org/{kind}/{source_id}",
    }
    if kind == "movie":
        crew = d.get("credits", {}).get("crew", [])
        fields |= {
            "year": _year(d.get("release_date")),
            "release_date": _date(d.get("release_date")),
            "runtime": d.get("runtime") or None,
            "total": 1,
            "creator": ", ".join(c["name"] for c in crew if c.get("job") == "Director"),
        }
        return fields

    runtimes = d.get("episode_run_time") or []
    episodes = []
    for season in d.get("seasons", [])[:60]:
        number = season.get("season_number")
        if not number:  # season 0 holds specials; they don't count towards progress
            continue
        s = _tmdb(f"/tv/{source_id}/season/{number}")
        for e in s.get("episodes", []):
            episodes.append(
                {
                    "season": number,
                    "number": e["episode_number"],
                    "title": e.get("name") or "",
                    "air_date": _date(e.get("air_date")),
                    "runtime": e.get("runtime") or None,
                }
            )
    next_episode = d.get("next_episode_to_air") or {}
    fields |= {
        "year": _year(d.get("first_air_date")),
        "release_date": _date(next_episode.get("air_date")) or _date(d.get("first_air_date")),
        "runtime": runtimes[0] if runtimes else None,
        "total": len(episodes) or d.get("number_of_episodes"),
        "creator": ", ".join(c["name"] for c in d.get("created_by", [])),
        "episodes": episodes,
    }
    return fields


def tmdb_recommendations(media_type, source_id):
    kind = _tmdb_type(media_type)
    data = _tmdb(f"/{kind}/{source_id}/recommendations")
    return [
        {
            "source": Source.TMDB,
            "source_id": str(r["id"]),
            "media_type": media_type,
            "title": r.get("title") or r.get("name") or "",
            "year": _year(r.get("release_date") or r.get("first_air_date")),
            "creator": "",
            "cover_url": f"{TMDB_IMAGES}{r['poster_path']}" if r.get("poster_path") else "",
        }
        for r in data.get("results", [])[:12]
    ]


def tmdb_find_imdb(imdb_id):
    """(media_type, tmdb id) for an IMDb id like tt0111161, or None."""
    data = _tmdb(f"/find/{imdb_id}", external_source="imdb_id")
    if data.get("movie_results"):
        return MediaType.MOVIE, str(data["movie_results"][0]["id"])
    if data.get("tv_results"):
        return MediaType.TV, str(data["tv_results"][0]["id"])
    return None


# AniList: anime and manga. No key needed.

ANILIST = "https://graphql.anilist.co"

ANILIST_FIELDS = """
  id siteUrl title { romaji english native } startDate { year month day } description(asHtml: false)
  genres episodes chapters duration status format coverImage { extraLarge large }
  studios(isMain: true) { nodes { name } } staff(perPage: 3) { nodes { name { full } } }
  nextAiringEpisode { airingAt episode }
"""


def _anilist(query, variables, timeout=None):
    body = json.dumps({"query": query, "variables": variables}).encode()
    data = _get_json(
        ANILIST, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=timeout
    )
    if data.get("errors"):
        raise ProviderError(data["errors"][0].get("message", "AniList error"))
    return data["data"]


def _anilist_title(m):
    t = m.get("title") or {}
    return t.get("english") or t.get("romaji") or t.get("native") or ""


def _anilist_creator(m, media_type):
    if media_type == MediaType.ANIME:
        return ", ".join(s["name"] for s in (m.get("studios") or {}).get("nodes", []))
    return ", ".join(s["name"]["full"] for s in (m.get("staff") or {}).get("nodes", [])[:2])


def _anilist_cover(m):
    cover = m.get("coverImage") or {}
    return cover.get("extraLarge") or cover.get("large") or ""


def anilist_search(media_type, query):
    kind = "ANIME" if media_type == MediaType.ANIME else "MANGA"
    data = _anilist(
        f"query ($q: String) {{ Page(perPage: 20) {{ media(search: $q, type: {kind}) {{ {ANILIST_FIELDS} }} }} }}",
        {"q": query},
    )
    return [
        {
            "source": Source.ANILIST,
            "source_id": str(m["id"]),
            "media_type": media_type,
            "title": _anilist_title(m),
            "year": (m.get("startDate") or {}).get("year"),
            "creator": _anilist_creator(m, media_type),
            "cover_url": _anilist_cover(m),
        }
        for m in data["Page"]["media"]
    ]


def anilist_fetch(media_type, source_id):
    data = _anilist(f"query ($id: Int) {{ Media(id: $id) {{ {ANILIST_FIELDS} }} }}", {"id": int(source_id)})
    m = data["Media"]
    start = m.get("startDate") or {}
    released = None
    if start.get("year"):
        released = date(start["year"], start.get("month") or 1, start.get("day") or 1)
    upcoming = m.get("nextAiringEpisode")
    if upcoming:
        released = date.fromtimestamp(upcoming["airingAt"])
    original = (m.get("title") or {}).get("native") or ""
    return {
        "title": _anilist_title(m),
        "original_title": original,
        "year": start.get("year"),
        "release_date": released,
        "creator": _anilist_creator(m, media_type),
        "description": _strip_tags(m.get("description") or ""),
        "genres": m.get("genres") or [],
        "runtime": m.get("duration") or None,
        "total": m.get("episodes") if media_type == MediaType.ANIME else m.get("chapters"),
        "status_text": (m.get("status") or "").replace("_", " ").capitalize(),
        "cover_url": _anilist_cover(m),
        "url": m.get("siteUrl") or "",
    }


def _strip_tags(text):
    """Plain text from a bit of HTML: line breaks kept, tags gone, &amp; and friends decoded."""
    text = re.sub(r"<br\s*/?>", "\n", text or "", flags=re.I)
    text = re.sub(r"</p>\s*<p>", "\n\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


# Open Library: books. No key needed.

OPENLIBRARY = "https://openlibrary.org"
OPENLIBRARY_TIMEOUT = 15  # Open Library is slow at times, but does answer
OPENLIBRARY_FIELDS = (
    "key,title,author_name,first_publish_year,cover_i,number_of_pages_median,subject,"
    "editions,editions.key,editions.title,editions.language,editions.cover_i"
)


def _openlibrary_edition(doc):
    """The English edition Open Library picked for this work (with lang=en), if there is one."""
    editions = (doc.get("editions") or {}).get("docs") or []
    return editions[0] if editions and "eng" in (editions[0].get("language") or []) else {}


def _openlibrary_title(doc):
    """The English title when there's an English edition: 'The Rings of Saturn', not 'Die Ringe des Saturn'."""
    return _openlibrary_edition(doc).get("title") or doc.get("title", "")


def _openlibrary_cover(doc):
    cover = _openlibrary_edition(doc).get("cover_i") or doc.get("cover_i")
    return f"https://covers.openlibrary.org/b/id/{cover}-L.jpg" if cover else ""


def _openlibrary_search(q, limit=20):
    params = {"q": q, "limit": limit, "fields": OPENLIBRARY_FIELDS, "lang": "en"}
    return _get_json(f"{OPENLIBRARY}/search.json", params=params, timeout=OPENLIBRARY_TIMEOUT).get("docs", [])


def openlibrary_search(media_type, query):
    return [
        {
            "source": Source.OPENLIBRARY,
            "source_id": doc["key"].rsplit("/", 1)[-1],
            "media_type": media_type,
            "title": _openlibrary_title(doc),
            "year": doc.get("first_publish_year"),
            "creator": ", ".join(doc.get("author_name", [])[:2]),
            "cover_url": _openlibrary_cover(doc),
        }
        for doc in _openlibrary_search(query)
        if doc.get("key")
    ]


def openlibrary_fetch(media_type, source_id):
    work = _get_json(f"{OPENLIBRARY}/works/{source_id}.json", timeout=OPENLIBRARY_TIMEOUT)
    found = _openlibrary_search(f"key:/works/{source_id}", limit=1)
    doc = found[0] if found else {}
    description = work.get("description") or ""
    if isinstance(description, dict):
        description = description.get("value", "")
    title = _openlibrary_title(doc) or work.get("title", "")
    return {
        "title": title,
        "original_title": work.get("title", "") if work.get("title") != title else "",
        "year": doc.get("first_publish_year"),
        "release_date": None,
        "creator": ", ".join(dict.fromkeys(doc.get("author_name", []))) if doc else "",
        "description": description,
        "genres": (doc.get("subject") or work.get("subjects") or [])[:6],
        "total": doc.get("number_of_pages_median"),
        "cover_url": _openlibrary_cover(doc)
        or (f"https://covers.openlibrary.org/b/id/{work['covers'][0]}-L.jpg" if work.get("covers") else ""),
        "url": f"{OPENLIBRARY}/works/{source_id}",
    }


# MusicBrainz: albums. No key needed, but no more than one request a second.

MUSICBRAINZ = "https://musicbrainz.org/ws/2"
_last_musicbrainz_call = [0.0]
_musicbrainz_lock = threading.Lock()


def _musicbrainz(path, timeout=None, **params):
    for attempt in range(2):
        with _musicbrainz_lock:
            wait = 1.0 + attempt - (time.monotonic() - _last_musicbrainz_call[0])
            if wait > 0:
                time.sleep(wait)
            _last_musicbrainz_call[0] = time.monotonic()
        try:
            return _get_json(f"{MUSICBRAINZ}{path}", params={**params, "fmt": "json"}, timeout=timeout)
        except ProviderError as error:
            # 503 means "slow down": wait a little longer and try once more.
            if attempt or "503" not in str(error):
                raise


def _artist(credits):
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits or [])


def _words(text):
    return set(re.findall(r"\w+", text.lower()))


def _musicbrainz_rank(groups, query):
    """MusicBrainz scores 'Joni Mitchell's Blue' (a tribute) above Blue by Joni Mitchell for 'joni mitchell blue'.
    Put the release groups whose title and artist together are exactly the words searched for first."""
    wanted = _words(query)

    def rank(g):
        title, artist = _words(g.get("title", "")), _words(_artist(g.get("artist-credit")))
        if title | artist == wanted and title and not title >= wanted:
            return 0
        if title == wanted:
            return 1
        return 2

    return sorted(groups, key=rank)  # sorted() is stable: within a rank MusicBrainz's order stays


def musicbrainz_search(media_type, query):
    data = _musicbrainz("/release-group", query=query, limit=25)
    return [
        {
            "source": Source.MUSICBRAINZ,
            "source_id": g["id"],
            "media_type": media_type,
            "title": g.get("title", ""),
            "year": _year(g.get("first-release-date")),
            "creator": _artist(g.get("artist-credit")),
            "cover_url": f"https://coverartarchive.org/release-group/{g['id']}/front-250",
        }
        for g in _musicbrainz_rank(data.get("release-groups", []), query)[:20]
    ]


def musicbrainz_fetch(media_type, source_id):
    g = _musicbrainz(f"/release-group/{source_id}", inc="artist-credits+genres+releases")
    tracks, minutes = None, None
    releases = g.get("releases") or []
    if releases:
        try:
            release = _musicbrainz(f"/release/{releases[0]['id']}", inc="recordings")
        except ProviderError:  # MusicBrainz is busy; the album is still worth adding without its tracks
            release = {}
        recordings = [t for medium in release.get("media", []) for t in medium.get("tracks", [])]
        tracks = len(recordings) or None
        length = sum(t.get("length") or 0 for t in recordings)
        minutes = round(length / 60000) or None
    return {
        "title": g.get("title", ""),
        "year": _year(g.get("first-release-date")),
        "release_date": _date(g.get("first-release-date")) if len(g.get("first-release-date", "")) == 10 else None,
        "creator": _artist(g.get("artist-credit")),
        "description": g.get("disambiguation", ""),
        "genres": [x["name"] for x in sorted(g.get("genres", []), key=lambda x: -x.get("count", 0))][:5],
        "runtime": minutes,
        "total": tracks,
        "cover_url": f"https://coverartarchive.org/release-group/{source_id}/front-250",
        "url": f"https://musicbrainz.org/release-group/{source_id}",
    }


# Apple Podcasts directory: podcasts. No key needed.

ITUNES = "https://itunes.apple.com"


def _podcast(r, media_type):
    return {
        "source": Source.ITUNES,
        "source_id": str(r["collectionId"]),
        "media_type": media_type,
        "title": r.get("collectionName", ""),
        "year": None,  # releaseDate is the newest episode, not when the podcast started
        "creator": r.get("artistName", ""),
        "cover_url": r.get("artworkUrl600") or r.get("artworkUrl100") or "",
    }


def itunes_search(media_type, query):
    data = _get_json(f"{ITUNES}/search", params={"media": "podcast", "term": query, "limit": 20})
    return [_podcast(r, media_type) for r in data.get("results", []) if r.get("collectionId")]


def itunes_fetch(media_type, source_id):
    results = _get_json(f"{ITUNES}/lookup", params={"id": source_id}).get("results", [])
    if not results:
        raise ProviderError("Podcast not found.")
    r = results[0]
    return {
        "title": r.get("collectionName", ""),
        "year": None,
        "release_date": None,
        "creator": r.get("artistName", ""),
        "description": "",
        "genres": [g for g in r.get("genres", []) if g != "Podcasts"],
        "total": r.get("trackCount"),
        "cover_url": r.get("artworkUrl600") or "",
        "url": r.get("collectionViewUrl", ""),
    }


# TVmaze: series, with seasons and episodes. No key needed (CC BY-SA; liveaux links back to every show).

TVMAZE = "https://api.tvmaze.com"


def _tvmaze_cover(show, size="original"):
    image = show.get("image") or {}
    return image.get(size) or image.get("medium") or image.get("original") or ""


def tvmaze_search(media_type, query):
    found = _get_json(f"{TVMAZE}/search/shows", params={"q": query})
    results = []
    for row in found[:20]:
        show = row.get("show") or {}
        channel = (show.get("network") or show.get("webChannel") or {}).get("name") or ""
        results.append(
            {
                "source": Source.TVMAZE,
                "source_id": str(show["id"]),
                "media_type": media_type,
                "title": show.get("name") or "",
                "year": _year(show.get("premiered")),
                "creator": channel,
                "cover_url": _tvmaze_cover(show, "medium"),
            }
        )
    return results


def tvmaze_fetch(media_type, source_id):
    show = _get_json(
        f"{TVMAZE}/shows/{int(source_id)}", params={"embed[]": ["episodes", "crew", "nextepisode"]}
    )
    embedded = show.get("_embedded") or {}
    episodes = [
        {
            "season": e["season"],
            "number": e["number"],
            "title": e.get("name") or "",
            "air_date": _date(e.get("airdate")),
            "runtime": e.get("runtime") or None,
        }
        for e in embedded.get("episodes") or []
        # Specials have no number, and season 0 doesn't count towards progress.
        if e.get("number") and e.get("season") and e.get("type", "regular") == "regular"
    ]
    creators = [c["person"]["name"] for c in embedded.get("crew") or [] if c.get("type") == "Creator"]
    next_episode = embedded.get("nextepisode") or {}
    return {
        "title": show.get("name") or "",
        "year": _year(show.get("premiered")),
        "release_date": _date(next_episode.get("airdate")) or _date(show.get("premiered")),
        "creator": ", ".join(dict.fromkeys(creators)),
        "description": _strip_tags(show.get("summary") or ""),
        "genres": show.get("genres") or [],
        "runtime": show.get("averageRuntime") or show.get("runtime") or None,
        "total": len(episodes) or None,
        "status_text": show.get("status") or "",
        "cover_url": _tvmaze_cover(show),
        "url": show.get("url") or f"https://www.tvmaze.com/shows/{source_id}",
        "episodes": episodes,
    }


# Wikidata and Wikipedia: films and games when there's no TMDB or IGDB key. No key needed.
# Wikidata is CC0. Descriptions come from the English Wikipedia (CC BY-SA) and say so.

WIKIDATA = "https://www.wikidata.org/w/api.php"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"
# What a search on Wikidata is narrowed to: instances of these classes, or anything with one of these ids.
WIKIDATA_KINDS = {
    # film, animated feature film, documentary film, short film, television film; or a TMDB film id
    MediaType.MOVIE: ["P31=Q11424", "P31=Q29168811", "P31=Q93204", "P31=Q24862", "P31=Q506240", "P4947"],
    # video game; or an IGDB id
    MediaType.GAME: ["P31=Q7889", "P5794"],
}
WIKIDATA_MINUTE, WIKIDATA_HOUR = "Q7727", "Q25235"


def _wikimedia(url, params, timeout=None):
    """Wikimedia's APIs answer 429 or 503 when they're busy: wait a moment and ask once more."""
    try:
        return _get_json(url, params=params, timeout=timeout)
    except ProviderError as error:
        if "503" not in str(error) and "429" not in str(error):
            raise
        time.sleep(1.5)
        return _get_json(url, params=params, timeout=timeout)


def _wikidata(timeout=None, **params):
    return _wikimedia(WIKIDATA, {**params, "format": "json", "formatversion": "2"}, timeout=timeout)


def wikidata_find(statement, timeout=None, limit=10):
    """Entity ids (Q…) matching a search, e.g. 'haswbstatement:P4947=976893' or 'perfect days haswbstatement:P31=Q11424'."""
    data = _wikidata(timeout, action="query", list="search", srsearch=statement, srlimit=limit, srprop="")
    return [r["title"] for r in data.get("query", {}).get("search", [])]


def wikidata_entities(ids, props="labels|claims|sitelinks", timeout=None):
    """{id: entity} for up to 50 ids."""
    if not ids:
        return {}
    data = _wikidata(
        timeout,
        action="wbgetentities",
        ids="|".join(ids[:50]),
        props=props,
        languages="en|mul",
        sitefilter="enwiki",
    )
    return {k: v for k, v in (data.get("entities") or {}).items() if "missing" not in v}


def wikidata_label(entity):
    labels = entity.get("labels") or {}
    return (labels.get("en") or labels.get("mul") or {}).get("value", "")


def wikidata_labels(ids, timeout=None):
    """{id: English label}, cached for a month: names of directors, genres and critics barely change."""
    labels, missing = {}, []
    for qid in dict.fromkeys(ids):
        cached = cache.get(f"wikidata-label:{qid}")
        if cached is None:
            missing.append(qid)
        else:
            labels[qid] = cached
    for start in range(0, len(missing), 50):
        for qid, entity in wikidata_entities(missing[start : start + 50], props="labels", timeout=timeout).items():
            labels[qid] = wikidata_label(entity)
            cache.set(f"wikidata-label:{qid}", labels[qid], 60 * 60 * 24 * 30)
    return labels


def wikidata_values(entity, prop):
    """The values of a property, best-ranked first and deprecated ones left out."""
    claims = [c for c in (entity.get("claims") or {}).get(prop, []) if c.get("rank") != "deprecated"]
    claims.sort(key=lambda c: c.get("rank") != "preferred")
    values = []
    for claim in claims:
        value = (claim.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if value is not None:
            values.append(value)
    return values


def _wikidata_ids(entity, prop):
    return [v["id"] for v in wikidata_values(entity, prop) if isinstance(v, dict) and v.get("id")]


def _wikidata_date(value):
    """(date or None, year or None) from a Wikidata time value; the date only when the day is known."""
    if not isinstance(value, dict) or not value.get("time"):
        return None, None
    match = re.match(r"([+-]\d+)-(\d\d)-(\d\d)", value["time"])
    if not match or match.group(1).startswith("-"):
        return None, None
    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if value.get("precision", 0) >= 11 and month and day:
        try:
            return date(year, month, day), year
        except ValueError:
            pass
    return None, year if value.get("precision", 0) >= 9 else None


def _wikidata_released(entity):
    """The first publication date: (date or None, year or None)."""
    found = [_wikidata_date(v) for v in wikidata_values(entity, "P577")]
    found = [f for f in found if f[1]]
    if not found:
        return None, None
    year = min(f[1] for f in found)
    days = [f[0] for f in found if f[0]]
    first = min(days) if days else None
    return (first if first and first.year == year else None), year


def _wikidata_minutes(entity):
    for value in wikidata_values(entity, "P2047"):
        try:
            amount = float(value["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        unit = value.get("unit", "").rsplit("/", 1)[-1]
        if unit == WIKIDATA_HOUR:
            amount *= 60
        elif unit not in (WIKIDATA_MINUTE, "1"):
            continue
        return round(amount) or None
    return None


def _enwiki_title(entity):
    return ((entity.get("sitelinks") or {}).get("enwiki") or {}).get("title", "")


def wikipedia_pages(titles, *, intro=False, timeout=None):
    """{title: {"extract", "image", "url"}} from the English Wikipedia: the lead section and its picture."""
    titles = [t for t in dict.fromkeys(titles) if t]
    if not titles:
        return {}
    params = {
        "action": "query",
        "titles": "|".join(titles[:20]),
        "prop": "pageimages|info" + ("|extracts" if intro else ""),
        "piprop": "thumbnail",
        "pithumbsize": 500,
        "pilicense": "any",
        "inprop": "url",
        "redirects": 1,
        "format": "json",
        "formatversion": "2",
    }
    if intro:
        params |= {"exintro": 1, "explaintext": 1, "exlimit": 20}
    data = _wikimedia(WIKIPEDIA, params, timeout=timeout).get("query", {})
    renamed = {r["to"]: r["from"] for r in data.get("normalized", []) + data.get("redirects", [])}
    pages = {}
    for page in data.get("pages", []):
        if page.get("missing"):
            continue
        image = (page.get("thumbnail") or {}).get("source", "").split("?")[0]
        info = {"extract": page.get("extract", ""), "image": image, "url": page.get("fullurl", "")}
        pages[page["title"]] = info
        if page["title"] in renamed:
            pages[renamed[page["title"]]] = info
    return pages


def _lead(text, words=90):
    """The first paragraphs of a Wikipedia lead, up to about `words` words, so the credit after it always shows."""
    kept, count = [], 0
    for paragraph in [p.strip() for p in (text or "").split("\n") if p.strip()]:
        if kept and count + len(paragraph.split()) > words:
            break
        kept.append(paragraph)
        count += len(paragraph.split())
    return "\n\n".join(kept)


def _commons_image(entity):
    for name in wikidata_values(entity, "P3383") + wikidata_values(entity, "P18") + wikidata_values(entity, "P154"):
        if isinstance(name, str):
            return "https://commons.wikimedia.org/wiki/Special:FilePath/" + urllib.parse.quote(name.replace(" ", "_")) + "?width=500"
    return ""


def _wikidata_creators(entity, media_type):
    return _wikidata_ids(entity, "P57" if media_type == MediaType.MOVIE else "P178")


def _genre_name(label):
    """'science fiction film' → 'Science fiction'. Wikidata's genres say what they're a genre of."""
    label = re.sub(r"\s+(film|video game|game|genre)$", "", label.strip())
    return label[:1].upper() + label[1:]


def wikidata_search(media_type, query):
    kinds = WIKIDATA_KINDS.get(media_type)
    if not kinds:
        return []
    statement = "|".join(kinds)
    query = re.sub(r"[\"\[\]|]", " ", query)
    ids = wikidata_find(f"{query} haswbstatement:{statement}")
    entities = wikidata_entities(ids)
    names = wikidata_labels([c for e in entities.values() for c in _wikidata_creators(e, media_type)[:2]])
    pages = wikipedia_pages([_enwiki_title(e) for e in entities.values()])
    results = []
    for qid in ids:
        entity = entities.get(qid)
        if not entity or not wikidata_label(entity):
            continue
        page = pages.get(_enwiki_title(entity)) or {}
        results.append(
            {
                "source": Source.WIKIDATA,
                "source_id": qid,
                "media_type": media_type,
                "title": wikidata_label(entity),
                "year": _wikidata_released(entity)[1],
                "creator": ", ".join(names.get(c, "") for c in _wikidata_creators(entity, media_type)[:2] if names.get(c)),
                "cover_url": page.get("image") or _commons_image(entity),
                "_rank": (wikidata_label(entity).casefold() != query.strip().casefold(), not page),
            }
        )
    # The search ranks 'Hades II' above 'Hades' for 'hades'. Exact titles first, then those with a Wikipedia page.
    results.sort(key=lambda r: r.pop("_rank"))
    return results


def wikidata_fetch(media_type, source_id):
    if not re.fullmatch(r"Q\d+", source_id or ""):
        raise ProviderError("That's not a Wikidata id.")
    entity = wikidata_entities([source_id]).get(source_id)
    if not entity:
        raise ProviderError("Not found on Wikidata.")
    creators = _wikidata_creators(entity, media_type)
    genres = _wikidata_ids(entity, "P136")
    names = wikidata_labels(creators[:4] + genres[:6])
    page = wikipedia_pages([_enwiki_title(entity)], intro=True).get(_enwiki_title(entity)) or {}
    released, year = _wikidata_released(entity)
    title = wikidata_label(entity)
    original = next((v.get("text", "") for v in wikidata_values(entity, "P1476") if isinstance(v, dict)), "")
    description = _lead(page.get("extract", ""))
    if description:
        description += "\n\nFrom Wikipedia (CC BY-SA 4.0)."
    fields = {
        "title": title,
        "original_title": original if original != title else "",
        "year": year,
        "release_date": released,
        "creator": ", ".join(names[c] for c in creators[:3] if names.get(c)),
        "description": description,
        "genres": list(dict.fromkeys(_genre_name(names[g]) for g in genres[:6] if names.get(g))),
        "cover_url": page.get("image") or _commons_image(entity),
        "url": page.get("url") or f"https://www.wikidata.org/wiki/{source_id}",
    }
    if media_type == MediaType.MOVIE:
        fields |= {"runtime": _wikidata_minutes(entity), "total": 1}
    return fields



# IGDB: games. Needs IGDB_CLIENT_ID and IGDB_CLIENT_SECRET (a Twitch developer app).

IGDB = "https://api.igdb.com/v4"
IGDB_FIELDS = (
    "fields name,first_release_date,cover.image_id,summary,genres.name,url,"
    "involved_companies.company.name,involved_companies.developer;"
)


def _igdb_token():
    token = cache.get("igdb-token")
    if token:
        return token
    data = _get_json(
        "https://id.twitch.tv/oauth2/token",
        params={
            "client_id": settings.IGDB_CLIENT_ID,
            "client_secret": settings.IGDB_CLIENT_SECRET,
            "grant_type": "client_credentials",
        },
        data=b"",
    )
    cache.set("igdb-token", data["access_token"], data.get("expires_in", 3600) - 60)
    return data["access_token"]


def _igdb(body):
    headers = {"Client-ID": settings.IGDB_CLIENT_ID, "Authorization": f"Bearer {_igdb_token()}"}
    return _get_json(f"{IGDB}/games", headers=headers, data=body.encode())


def _igdb_result(g, media_type):
    released = date.fromtimestamp(g["first_release_date"]) if g.get("first_release_date") else None
    image = (g.get("cover") or {}).get("image_id")
    developers = [c["company"]["name"] for c in g.get("involved_companies", []) if c.get("developer")]
    return {
        "source": Source.IGDB,
        "source_id": str(g["id"]),
        "media_type": media_type,
        "title": g.get("name", ""),
        "year": released.year if released else None,
        "creator": ", ".join(developers[:2]),
        "cover_url": f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image}.jpg" if image else "",
        "release_date": released,
        "description": g.get("summary", ""),
        "genres": [x["name"] for x in g.get("genres", [])],
        "url": g.get("url", ""),
    }


def igdb_search(media_type, query):
    query = query.replace('"', "")
    return [
        {k: v for k, v in _igdb_result(g, media_type).items() if k not in ("release_date", "description", "genres", "url")}
        for g in _igdb(f'search "{query}"; {IGDB_FIELDS} limit 20;')
    ]


def igdb_fetch(media_type, source_id):
    games = _igdb(f"{IGDB_FIELDS} where id = {int(source_id)};")
    if not games:
        raise ProviderError("Game not found.")
    result = _igdb_result(games[0], media_type)
    for key in ("source", "source_id", "media_type"):
        result.pop(key)
    return result


PROVIDERS = {
    Source.TMDB: (tmdb_search, tmdb_fetch),
    Source.ANILIST: (anilist_search, anilist_fetch),
    Source.OPENLIBRARY: (openlibrary_search, openlibrary_fetch),
    Source.MUSICBRAINZ: (musicbrainz_search, musicbrainz_fetch),
    Source.ITUNES: (itunes_search, itunes_fetch),
    Source.IGDB: (igdb_search, igdb_fetch),
    Source.TVMAZE: (tvmaze_search, tvmaze_fetch),
    Source.WIKIDATA: (wikidata_search, wikidata_fetch),
}


def igdb_configured():
    return bool(settings.IGDB_CLIENT_ID and settings.IGDB_CLIENT_SECRET)


def source_for(media_type):
    """The source liveaux searches for this kind of media, or None when it can only be added by hand."""
    return {
        MediaType.MOVIE: Source.TMDB if settings.TMDB_API_KEY else Source.WIKIDATA,
        MediaType.TV: Source.TMDB if settings.TMDB_API_KEY else Source.TVMAZE,
        MediaType.ANIME: Source.ANILIST,
        MediaType.MANGA: Source.ANILIST,
        MediaType.BOOK: Source.OPENLIBRARY,
        MediaType.MUSIC: Source.MUSICBRAINZ,
        MediaType.PODCAST: Source.ITUNES,
        MediaType.GAME: Source.IGDB if igdb_configured() else Source.WIKIDATA,
    }.get(media_type)


def search(media_type, query):
    source = source_for(media_type)
    if source is None or not query.strip():
        return []
    key = "library-search:" + hashlib.sha256(f"{source}:{media_type}:{query.strip().lower()}".encode()).hexdigest()
    results = cache.get(key)
    if results is None:
        results = PROVIDERS[source][0](media_type, query.strip())
        cache.set(key, results, 60 * 60)
    return results


def fetch(source, media_type, source_id):
    if source not in PROVIDERS:
        raise ProviderError("Unknown source.")
    return PROVIDERS[source][1](media_type, source_id)


# Covers are fetched from these hosts only, so the cover proxy can't be pointed at anything else.
COVER_HOSTS = (
    "image.tmdb.org",
    "s4.anilist.co",
    "covers.openlibrary.org",
    "coverartarchive.org",
    "images.igdb.com",
    ".mzstatic.com",
    "static.tvmaze.com",
    "upload.wikimedia.org",
    "commons.wikimedia.org",
)
MAX_COVER_BYTES = 3 * 1024 * 1024


def cover_allowed(url):
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(host == h or (h.startswith(".") and host.endswith(h)) for h in COVER_HOSTS)


def fetch_cover(url):
    """(bytes, content type) of a cover image, or raises ProviderError."""
    if not cover_allowed(url):
        raise ProviderError("Covers only come from known sources.")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            content_type = response.headers.get_content_type()
            body = response.read(MAX_COVER_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise ProviderError(str(error)) from error
    if not content_type.startswith("image/") or len(body) > MAX_COVER_BYTES:
        raise ProviderError("That's not a cover.")
    return body, content_type

"""Where details about films, series, books and the rest come from.

Every provider turns its API into the same shape:

- `search(media_type, query)` returns a list of results:
  {"source", "source_id", "media_type", "title", "year", "creator", "cover_url"}
- `fetch(media_type, source_id)` returns the fields for an `Item`, plus "episodes" for series:
  [{"season", "number", "title", "air_date", "runtime"}]

All calls happen on the server, so visitors' browsers never talk to these services.
"""

import hashlib
import json
import logging
import re
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


def _request(url, *, params=None, headers=None, data=None):
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("Request to %s failed: %s", url.split("?")[0], error)
        raise ProviderError(str(error)) from error


def _get_json(url, *, params=None, headers=None, data=None):
    body = _request(url, params=params, headers=headers, data=data)
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


def _tmdb(path, **params):
    key = settings.TMDB_API_KEY
    headers = {}
    if len(key) > 40:  # a v4 read access token
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    return _get_json(f"{TMDB}{path}", params=params, headers=headers)


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
  genres episodes chapters duration status format coverImage { large }
  studios(isMain: true) { nodes { name } } staff(perPage: 3) { nodes { name { full } } }
  nextAiringEpisode { airingAt episode }
"""


def _anilist(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    data = _get_json(ANILIST, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"})
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
            "cover_url": (m.get("coverImage") or {}).get("large") or "",
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
        "cover_url": (m.get("coverImage") or {}).get("large") or "",
        "url": m.get("siteUrl") or "",
    }


def _strip_tags(text):
    return re.sub(r"<[^>]+>", "", text).strip()


# Open Library: books. No key needed.

OPENLIBRARY = "https://openlibrary.org"
OPENLIBRARY_FIELDS = "key,title,author_name,first_publish_year,cover_i,number_of_pages_median,subject"


def _openlibrary_cover(doc):
    return f"https://covers.openlibrary.org/b/id/{doc['cover_i']}-L.jpg" if doc.get("cover_i") else ""


def openlibrary_search(media_type, query):
    data = _get_json(f"{OPENLIBRARY}/search.json", params={"q": query, "limit": 20, "fields": OPENLIBRARY_FIELDS})
    return [
        {
            "source": Source.OPENLIBRARY,
            "source_id": doc["key"].rsplit("/", 1)[-1],
            "media_type": media_type,
            "title": doc.get("title", ""),
            "year": doc.get("first_publish_year"),
            "creator": ", ".join(doc.get("author_name", [])[:2]),
            "cover_url": _openlibrary_cover(doc),
        }
        for doc in data.get("docs", [])
    ]


def openlibrary_fetch(media_type, source_id):
    work = _get_json(f"{OPENLIBRARY}/works/{source_id}.json")
    found = _get_json(
        f"{OPENLIBRARY}/search.json", params={"q": f"key:/works/{source_id}", "fields": OPENLIBRARY_FIELDS}
    ).get("docs", [{}])
    doc = found[0] if found else {}
    description = work.get("description") or ""
    if isinstance(description, dict):
        description = description.get("value", "")
    return {
        "title": work.get("title") or doc.get("title", ""),
        "year": doc.get("first_publish_year"),
        "release_date": None,
        "creator": ", ".join(doc.get("author_name", [])[:3]),
        "description": description,
        "genres": (doc.get("subject") or work.get("subjects") or [])[:6],
        "total": doc.get("number_of_pages_median"),
        "cover_url": _openlibrary_cover(doc),
        "url": f"{OPENLIBRARY}/works/{source_id}",
    }


# MusicBrainz: albums. No key needed, but no more than one request a second.

MUSICBRAINZ = "https://musicbrainz.org/ws/2"
_last_musicbrainz_call = [0.0]


def _musicbrainz(path, **params):
    for attempt in range(2):
        wait = 1.0 + attempt - (time.monotonic() - _last_musicbrainz_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_musicbrainz_call[0] = time.monotonic()
        try:
            return _get_json(f"{MUSICBRAINZ}{path}", params={**params, "fmt": "json"})
        except ProviderError as error:
            # 503 means "slow down": wait a little longer and try once more.
            if attempt or "503" not in str(error):
                raise


def _artist(credits):
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits or [])


def musicbrainz_search(media_type, query):
    data = _musicbrainz("/release-group", query=query, limit=20)
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
        for g in data.get("release-groups", [])
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
        "year": _year(r.get("releaseDate")),
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
}


def source_for(media_type):
    """The source liveaux searches for this kind of media, or None when it can only be added by hand."""
    return {
        MediaType.MOVIE: Source.TMDB if settings.TMDB_API_KEY else None,
        MediaType.TV: Source.TMDB if settings.TMDB_API_KEY else None,
        MediaType.ANIME: Source.ANILIST,
        MediaType.MANGA: Source.ANILIST,
        MediaType.BOOK: Source.OPENLIBRARY,
        MediaType.MUSIC: Source.MUSICBRAINZ,
        MediaType.PODCAST: Source.ITUNES,
        MediaType.GAME: Source.IGDB if settings.IGDB_CLIENT_ID and settings.IGDB_CLIENT_SECRET else None,
    }.get(media_type)


def search(media_type, query):
    source = source_for(media_type)
    if source is None or not query.strip():
        return []
    key = "library-search:" + hashlib.sha256(f"{media_type}:{query.strip().lower()}".encode()).hexdigest()
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

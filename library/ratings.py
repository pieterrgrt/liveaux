"""Elsewhere: what other sites say about an item, next to what people on liveaux think.

Only official APIs and open data, each named and linked: Wikidata (CC0) for the review scores it records
(Rotten Tomatoes, Metacritic, IMDb, OpenCritic…), and the APIs of TMDB, TVmaze, AniList, Open Library,
MusicBrainz and IGDB. No pages are scraped. Everything is fetched on the server, so visitors' browsers
never talk to these sites.

Scores are kept in `ExternalRating` and fetched again when they're older than STALE_AFTER: on the item
page (through a small script, so the page itself never waits) and in `refresh_library`.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from . import providers
from .models import Entry, ExternalRating, MediaType, Source

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=6)
TIMEOUT = 5  # seconds per request: a slow site just doesn't show up this time

# The Wikidata property that holds each source's id, so liveaux can find the item on Wikidata.
WIKIDATA_ID_PROPERTY = {
    (Source.TMDB, MediaType.MOVIE): "P4947",
    (Source.TMDB, MediaType.TV): "P4983",
    (Source.TVMAZE, MediaType.TV): "P8600",
    (Source.ANILIST, MediaType.ANIME): "P8729",
    (Source.ANILIST, MediaType.MANGA): "P8731",
    (Source.OPENLIBRARY, MediaType.BOOK): "P648",
    (Source.MUSICBRAINZ, MediaType.MUSIC): "P436",
    (Source.ITUNES, MediaType.PODCAST): "P5842",
    (Source.IGDB, MediaType.GAME): "P5794",
}

# Who gave a review score on Wikidata (P447), and where their page for the work is.
REVIEWERS = {
    "Q105584": ("P1258", "https://www.rottentomatoes.com/{}"),  # Rotten Tomatoes
    "Q150248": ("P1712", "https://www.metacritic.com/{}"),  # Metacritic
    "Q37312": ("P345", "https://www.imdb.com/title/{}/"),  # IMDb
    "Q21039459": ("P2864", "https://opencritic.com/game/{}"),  # OpenCritic
}
COUNT_UNITS = {"Q80698083": "critic reviews", "Q137041451": "user ratings"}
METHOD_NAMES = {"Q107218751": "User rating"}  # IMDb's 'weighted average


def _number(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_score(text):
    """(value, scale) from how Wikidata writes a score: '96%', '80/100', '7.8/10', '4/5 stars'."""
    text = (text or "").strip()
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*%", text)
    if match:
        return _number(match.group(1).replace(",", ".")), 100.0
    match = re.match(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)", text)
    if match:
        value, scale = _number(match.group(1).replace(",", ".")), _number(match.group(2).replace(",", "."))
        if scale:
            return value, scale
    return None, None


def _show(value, scale):
    """'7.8/10', '96%', '4.1/5'."""
    if value is None:
        return ""
    if scale == 100:
        return f"{round(value)}%"
    shown = f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{shown}/{scale:g}"


def _amount(value):
    try:
        return int(float(value["amount"]))
    except (KeyError, TypeError, ValueError):
        return None


# Finding the item on Wikidata


def wikidata_id(item):
    """The Wikidata id (Q…) of the item, or "". Remembered for a month (a day when there's none)."""
    if item.source == Source.WIKIDATA:
        return item.source_id
    prop = WIKIDATA_ID_PROPERTY.get((item.source, item.media_type))
    value = item.source_id
    if item.source == Source.IGDB:
        value = item.url.rstrip("/").rsplit("/", 1)[-1] if "/games/" in item.url else ""
    if not prop or not re.fullmatch(r"[\w.-]+", value or ""):
        return ""
    key = f"elsewhere-qid:{item.source}:{item.media_type}:{value}"
    qid = cache.get(key)
    if qid is None:
        found = providers.wikidata_find(f"haswbstatement:{prop}={value}", timeout=TIMEOUT, limit=1)
        qid = found[0] if found else ""
        cache.set(key, qid, 60 * 60 * 24 * (30 if qid else 1))
    return qid


def _first(entity, prop):
    values = [v for v in providers.wikidata_values(entity, prop) if isinstance(v, str)] if entity else []
    return values[0] if values else ""


def _ids(item, entity):
    """The item's id at each source: from the item itself, else from Wikidata."""
    ids = {
        "tmdb": _first(entity, "P4947" if item.media_type == MediaType.MOVIE else "P4983"),
        "tvmaze": _first(entity, "P8600"),
        "anilist": _first(entity, "P8731" if item.media_type == MediaType.MANGA else "P8729"),
        "openlibrary": next(
            (v for v in providers.wikidata_values(entity, "P648") if isinstance(v, str) and v.endswith("W")), ""
        )
        if entity
        else "",
        "musicbrainz": _first(entity, "P436"),
        "igdb": "",
    }
    own = {
        Source.TMDB: "tmdb",
        Source.TVMAZE: "tvmaze",
        Source.ANILIST: "anilist",
        Source.OPENLIBRARY: "openlibrary",
        Source.MUSICBRAINZ: "musicbrainz",
        Source.IGDB: "igdb",
    }.get(item.source)
    if own:
        ids[own] = item.source_id
    return ids


# The sources. Each returns a list of rows (dicts with ExternalRating's fields), or raises ProviderError.


def from_wikidata(item, entity):
    """Review scores recorded on Wikidata (P444), with who gave them (P447), how (P459), when (P585)
    and out of how many reviews (P7887). Only the newest score per critic and method."""
    if not entity:
        return []
    qid = entity["id"]
    newest = {}
    for claim in (entity.get("claims") or {}).get("P444", []):
        if claim.get("rank") == "deprecated":
            continue
        text = (claim.get("mainsnak") or {}).get("datavalue", {}).get("value")
        qualifiers = claim.get("qualifiers") or {}

        def qualifier(prop):
            snaks = qualifiers.get(prop) or []
            return (snaks[0].get("datavalue") or {}).get("value") if snaks else None

        reviewer = (qualifier("P447") or {}).get("id")
        if not reviewer or not isinstance(text, str):
            continue
        method = (qualifier("P459") or {}).get("id", "")
        as_of = providers._wikidata_date(qualifier("P585"))[0]
        count = qualifier("P7887")
        row = {
            "reviewer": reviewer,
            "method": method,
            "text": text,
            "as_of": as_of,
            "count": _amount(count) if count else None,
            "unit": (count or {}).get("unit", "").rsplit("/", 1)[-1] if count else "",
            "preferred": claim.get("rank") == "preferred",
        }
        key = (reviewer, method)
        old = newest.get(key)
        if old is None or (row["preferred"], row["as_of"] or date.min) > (old["preferred"], old["as_of"] or date.min):
            newest[key] = row
    if not newest:
        return []
    names = providers.wikidata_labels(
        [r["reviewer"] for r in newest.values()] + [r["method"] for r in newest.values() if r["method"]],
        timeout=TIMEOUT,
    )
    rows = []
    for (reviewer, method), r in newest.items():
        value, scale = parse_score(r["text"])
        url = f"https://www.wikidata.org/wiki/{qid}#P444"
        if reviewer in REVIEWERS:
            prop, pattern = REVIEWERS[reviewer]
            external = _first(entity, prop)
            if external:
                url = pattern.format(external)
        label = names.get(reviewer) or "Critics"
        detail = METHOD_NAMES.get(method) or (names.get(method, "") if method else "")
        if detail.casefold().startswith(label.casefold() + " "):  # 'OpenCritic Top Critic Average' under OpenCritic
            detail = detail[len(label) + 1 :]
        rows.append(
            {
                "key": f"wikidata:{reviewer}:{method}",
                "source": "Wikidata",
                "label": label,
                "detail": detail[:1].upper() + detail[1:],
                "value": value,
                "scale": scale,
                # As the critic writes it (96%, 80/100, 7.8/10), unless that's 4.661157024793388/5.
                "display": r["text"].strip()[:40] if value is None or len(r["text"].strip()) <= 8 else _show(value, scale),
                "count": r["count"],
                "count_label": COUNT_UNITS.get(r["unit"], "ratings") if r["count"] else "",
                "url": url,
                "as_of": r["as_of"],
            }
        )
    order = list(REVIEWERS)
    rows.sort(key=lambda r: (order.index(r["key"].split(":")[1]) if r["key"].split(":")[1] in order else 99))
    return rows


def from_tmdb(item, tmdb_id):
    if not settings.TMDB_API_KEY or not tmdb_id or item.media_type not in (MediaType.MOVIE, MediaType.TV):
        return []
    kind = "movie" if item.media_type == MediaType.MOVIE else "tv"
    data = providers._tmdb(f"/{kind}/{int(tmdb_id)}", timeout=TIMEOUT)
    if not data.get("vote_count"):
        return []
    value = float(data.get("vote_average") or 0)
    return [
        {
            "key": "tmdb",
            "source": "TMDB",
            "label": "TMDB",
            "detail": "User score",
            "value": value,
            "scale": 10.0,
            "display": _show(value, 10.0),
            "count": data["vote_count"],
            "count_label": "votes",
            "url": f"https://www.themoviedb.org/{kind}/{int(tmdb_id)}",
        }
    ]


def from_tvmaze(item, tvmaze_id):
    if not tvmaze_id or item.media_type != MediaType.TV:
        return []
    show = providers._get_json(f"{providers.TVMAZE}/shows/{int(tvmaze_id)}", timeout=TIMEOUT)
    value = (show.get("rating") or {}).get("average")
    if value is None:
        return []
    return [
        {
            "key": "tvmaze",
            "source": "TVmaze",
            "label": "TVmaze",
            "detail": "Average rating",
            "value": float(value),
            "scale": 10.0,
            "display": _show(float(value), 10.0),
            "url": show.get("url") or f"https://www.tvmaze.com/shows/{int(tvmaze_id)}",
        }
    ]


def from_anilist(item, anilist_id):
    if not anilist_id or item.media_type not in (MediaType.ANIME, MediaType.MANGA):
        return []
    data = providers._anilist(
        "query ($id: Int) { Media(id: $id) { siteUrl averageScore meanScore popularity favourites } }",
        {"id": int(anilist_id)},
        timeout=TIMEOUT,
    )
    m = data.get("Media") or {}
    score = m.get("averageScore") or m.get("meanScore")
    if not score:
        return []
    return [
        {
            "key": "anilist",
            "source": "AniList",
            "label": "AniList",
            "detail": "Average score" if m.get("averageScore") else "Mean score",
            "value": float(score),
            "scale": 100.0,
            "display": f"{score}%",
            "count": m.get("popularity"),
            "count_label": "on lists" if m.get("popularity") else "",
            "extra": {"favourites": m.get("favourites")} if m.get("favourites") else {},
            "url": m.get("siteUrl") or "",
        }
    ]


def from_openlibrary(item, work_id):
    if not work_id or item.media_type != MediaType.BOOK or not re.fullmatch(r"OL\d+W", work_id):
        return []
    base = f"{providers.OPENLIBRARY}/works/{work_id}"
    ratings = providers._get_json(f"{base}/ratings.json", timeout=TIMEOUT)
    try:
        shelves = providers._get_json(f"{base}/bookshelves.json", timeout=TIMEOUT).get("counts") or {}
    except providers.ProviderError:
        shelves = {}
    summary = ratings.get("summary") or {}
    count = summary.get("count") or 0
    shelves = {k: shelves.get(k) or 0 for k in ("want_to_read", "currently_reading", "already_read")}
    if not count and not any(shelves.values()):
        return []
    value = float(summary["average"]) if count and summary.get("average") is not None else None
    return [
        {
            "key": "openlibrary",
            "source": "Open Library",
            "label": "Open Library",
            "detail": "Readers' rating",
            "value": value,
            "scale": 5.0 if value is not None else None,
            "display": _show(value, 5.0) if value is not None else "",
            "count": count or None,
            "count_label": "ratings" if count else "",
            "extra": {"shelves": shelves} if any(shelves.values()) else {},
            "url": base,
        }
    ]


def from_musicbrainz(item, group_id):
    if not group_id or item.media_type != MediaType.MUSIC:
        return []
    group = providers._musicbrainz(f"/release-group/{group_id}", inc="ratings", timeout=TIMEOUT)
    rating = group.get("rating") or {}
    if not rating.get("votes-count") or rating.get("value") is None:
        return []
    value = float(rating["value"])
    return [
        {
            "key": "musicbrainz",
            "source": "MusicBrainz",
            "label": "MusicBrainz",
            "detail": "Listeners' rating",
            "value": value,
            "scale": 5.0,
            "display": _show(value, 5.0),
            "count": rating["votes-count"],
            "count_label": "votes",
            "url": f"https://musicbrainz.org/release-group/{group_id}",
        }
    ]


def from_igdb(item, igdb_id):
    if not providers.igdb_configured() or not igdb_id or item.media_type != MediaType.GAME:
        return []
    games = providers._igdb(
        f"fields url,rating,rating_count,aggregated_rating,aggregated_rating_count; where id = {int(igdb_id)};"
    )
    if not games:
        return []
    g = games[0]
    rows = []
    for key, label, field in (("igdb", "IGDB", "rating"), ("igdb-critics", "IGDB critics", "aggregated_rating")):
        if g.get(field) is not None and g.get(f"{field}_count"):
            rows.append(
                {
                    "key": key,
                    "source": "IGDB",
                    "label": label,
                    "detail": "Players' rating" if field == "rating" else "Critics' average",
                    "value": float(g[field]),
                    "scale": 100.0,
                    "display": f"{round(g[field])}%",
                    "count": g[f"{field}_count"],
                    "count_label": "ratings" if field == "rating" else "reviews",
                    "url": g.get("url") or "",
                }
            )
    return rows


# Fetching, storing and showing


def checked_at(item):
    """When liveaux last looked, or None."""
    checked = cache.get(f"elsewhere-checked:{item.pk}")
    if checked:
        return checked
    latest = item.external_ratings.order_by("-fetched_at").values_list("fetched_at", flat=True).first()
    return latest


def is_stale(item):
    if item.is_manual:
        return False
    checked = checked_at(item)
    return checked is None or timezone.now() - checked > STALE_AFTER


def collect(item):
    """{source name: rows or None when it failed} from every source that knows the item."""
    results = {}
    try:
        qid = wikidata_id(item)
        entity = providers.wikidata_entities([qid], props="claims", timeout=TIMEOUT).get(qid) if qid else None
    except providers.ProviderError as error:
        log.info("Elsewhere: Wikidata for %s: %s", item, error)
        qid, entity, results["wikidata"] = "", None, None
    ids = _ids(item, entity)
    jobs = {
        "wikidata": (from_wikidata, entity),
        "tmdb": (from_tmdb, ids["tmdb"]),
        "tvmaze": (from_tvmaze, ids["tvmaze"]),
        "anilist": (from_anilist, ids["anilist"]),
        "openlibrary": (from_openlibrary, ids["openlibrary"]),
        "musicbrainz": (from_musicbrainz, ids["musicbrainz"]),
        "igdb": (from_igdb, ids["igdb"]),
    }
    if "wikidata" in results:
        jobs.pop("wikidata")

    def run(name):
        function, argument = jobs[name]
        try:
            return name, function(item, argument)
        except (providers.ProviderError, KeyError, TypeError, ValueError) as error:
            log.info("Elsewhere: %s for %s: %s", name, item, error)
            return name, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results.update(pool.map(run, jobs))
    return results


ORDER = ["wikidata", "tmdb", "tvmaze", "anilist", "openlibrary", "musicbrainz", "igdb"]
FIELDS = ("source", "label", "detail", "value", "scale", "display", "count", "count_label", "extra", "url", "as_of")


@transaction.atomic
def store(item, results):
    now = timezone.now()
    for name, rows in results.items():
        if rows is None:  # that source failed: keep what it said last time
            continue
        prefix = "wikidata:" if name == "wikidata" else name
        existing = item.external_ratings.filter(key__startswith=prefix)
        keep = []
        for position, row in enumerate(rows):
            defaults = {f: row.get(f) for f in FIELDS}
            defaults["extra"] = defaults["extra"] or {}
            for text in ("detail", "display", "count_label", "url"):
                defaults[text] = (defaults[text] or "")[: 500 if text == "url" else 40 if text != "detail" else 120]
            defaults["label"] = (defaults["label"] or "")[:120]
            if defaults["count"] == 1 and defaults["count_label"].endswith("s"):  # 1 rating, not 1 ratings
                defaults["count_label"] = defaults["count_label"][:-1]
            defaults |= {"position": ORDER.index(name) * 20 + position, "fetched_at": now}
            ExternalRating.objects.update_or_create(item=item, key=row["key"][:120], defaults=defaults)
            keep.append(row["key"][:120])
        existing.exclude(key__in=keep).delete()


def refresh(item, force=False):
    """Fetch the scores again when they're stale. Never raises: a source that fails is skipped."""
    if item.is_manual or (not force and not is_stale(item)):
        return False
    if not cache.add(f"elsewhere-lock:{item.pk}", 1, 60):  # someone else is fetching right now
        return False
    try:
        store(item, collect(item))
        cache.set(f"elsewhere-checked:{item.pk}", timezone.now(), int(STALE_AFTER.total_seconds() * 4))
    except Exception:  # never break the page over someone else's scores
        log.exception("Elsewhere failed for %s", item)
        return False
    finally:
        cache.delete(f"elsewhere-lock:{item.pk}")
    return True


def community(item):
    """The average score people on liveaux gave it, and how many did."""
    found = Entry.objects.filter(item=item, score__isnull=False).aggregate(average=Avg("score"), count=Count("id"))
    if not found["count"]:
        return None
    average = found["average"]
    return {
        "value": average,
        "display": _show(average, 10.0),
        "count": found["count"],
        "percent": round(10 * average),
    }


def summary(item):
    """What the Elsewhere block shows, from what's stored: no requests."""
    rows = list(item.external_ratings.all())
    updated = checked_at(item)
    return {
        "rows": rows,
        "sources": list(dict.fromkeys(r.source for r in rows)),
        "community": community(item),
        "updated": updated,
        "just_now": bool(updated) and timezone.now() - updated < timedelta(minutes=1),
        "stale": is_stale(item),
        "manual": item.is_manual,
    }

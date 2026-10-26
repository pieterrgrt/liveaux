"""Check-ins that arrive by themselves: from Plex, Jellyfin, or anything that talks to the API."""

import json
import logging

from django.conf import settings

from . import providers, services
from .models import Episode, Item, MediaType, Play, Source

log = logging.getLogger(__name__)


def _find(user, media_type, title, year=None):
    """Something the user already tracks, or that liveaux knows, by title."""
    if not title:
        return None
    mine = user.library_entries.filter(item__media_type=media_type, item__title__iexact=title).select_related("item")
    if year:
        mine = mine.filter(item__year=year) or mine
    if mine:
        return mine[0].item
    known = Item.objects.filter(media_type=media_type, title__iexact=title).exclude(source=Source.MANUAL)
    if year:
        known = known.filter(year=year)
    return known.first()


def resolve(user, *, media_type, title, year=None, tmdb_id=None, season=None, number=None):
    """(item, episode) for a play reported by a media server. Creates what's missing."""
    item = None
    if tmdb_id and media_type == MediaType.MOVIE:
        item = Item.objects.filter(source=Source.TMDB, media_type=media_type, source_id=str(tmdb_id)).first()
        if item is None and settings.TMDB_API_KEY:
            try:
                item = services.get_or_create_item(Source.TMDB, media_type, str(tmdb_id))
            except providers.ProviderError:
                item = None
    item = item or _find(user, media_type, title, year)
    if item is None and settings.TMDB_API_KEY and media_type in (MediaType.MOVIE, MediaType.TV) and title:
        try:
            results = providers.search(media_type, title)
            if year and media_type == MediaType.MOVIE:
                results = [r for r in results if r["year"] == year] or results
            if results:
                item = services.get_or_create_item(Source.TMDB, media_type, results[0]["source_id"])
        except providers.ProviderError:
            item = None
    if item is None:
        item = Item.objects.create(media_type=media_type, title=title or "Untitled", year=year, created_by=user)

    episode = None
    if media_type == MediaType.TV and season is not None and number is not None:
        episode = item.episodes.filter(season=season, number=number).first()
        if episode is None and item.is_manual:
            episode, _ = Episode.objects.get_or_create(item=item, season=season, number=number)
    return item, episode


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def plex(user, request):
    """Plex sends a multipart form with a JSON `payload` field. We log `media.scrobble`: watched past 90%."""
    try:
        payload = json.loads(request.POST.get("payload", ""))
    except ValueError:
        return None
    if payload.get("event") != "media.scrobble":
        return None
    meta = payload.get("Metadata") or {}
    kind = meta.get("type")
    guids = {g.get("id", "").split("://")[0]: g.get("id", "").split("://")[-1] for g in meta.get("Guid") or []}
    if kind == "movie":
        item, episode = resolve(
            user, media_type=MediaType.MOVIE, title=meta.get("title"), year=_int(meta.get("year")), tmdb_id=guids.get("tmdb")
        )
    elif kind == "episode":
        item, episode = resolve(
            user,
            media_type=MediaType.TV,
            title=meta.get("grandparentTitle"),
            season=_int(meta.get("parentIndex")),
            number=_int(meta.get("index")),
        )
    else:
        return None
    return services.check_in(user, item, episode=episode, via=Play.Via.PLEX)


def jellyfin(user, request):
    """The Jellyfin webhook plugin, with the 'Playback Stop' notification and its default JSON template."""
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return None
    if payload.get("NotificationType") != "PlaybackStop" or not payload.get("PlayedToCompletion"):
        return None
    kind = payload.get("ItemType")
    if kind == "Movie":
        item, episode = resolve(
            user,
            media_type=MediaType.MOVIE,
            title=payload.get("Name"),
            year=_int(payload.get("Year")),
            tmdb_id=payload.get("Provider_tmdb"),
        )
    elif kind == "Episode":
        item, episode = resolve(
            user,
            media_type=MediaType.TV,
            title=payload.get("SeriesName"),
            season=_int(payload.get("SeasonNumber")),
            number=_int(payload.get("EpisodeNumber")),
        )
    else:
        return None
    return services.check_in(user, item, episode=episode, via=Play.Via.JELLYFIN)

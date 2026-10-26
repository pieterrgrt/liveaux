"""What happens when someone adds, checks in or imports something. Views, webhooks and the API share these."""

import logging
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import providers
from .models import Entry, Episode, Item, MediaType, Play, Source, Status

log = logging.getLogger(__name__)

ITEM_FIELDS = (
    "title",
    "original_title",
    "year",
    "release_date",
    "creator",
    "description",
    "genres",
    "runtime",
    "total",
    "status_text",
    "url",
    "cover_url",
)


def _apply(item, data):
    for field in ITEM_FIELDS:
        if field in data and data[field] is not None:
            setattr(item, field, data[field])
    item.title = item.title[:300] or "Untitled"
    item.original_title = item.original_title[:300]
    item.creator = item.creator[:300]
    item.status_text = item.status_text[:60]
    if item.original_title == item.title:
        item.original_title = ""
    item.refreshed_at = timezone.now()


def _save_episodes(item, episodes):
    for e in episodes:
        Episode.objects.update_or_create(
            item=item,
            season=e["season"],
            number=e["number"],
            defaults={"title": e["title"][:300], "air_date": e["air_date"], "runtime": e["runtime"]},
        )


def get_or_create_item(source, media_type, source_id):
    """The item for this source and id, fetching its details the first time. Raises ProviderError."""
    item = Item.objects.filter(source=source, media_type=media_type, source_id=source_id).first()
    if item:
        return item
    data = providers.fetch(source, media_type, source_id)
    with transaction.atomic():
        item, created = Item.objects.get_or_create(source=source, media_type=media_type, source_id=source_id)
        if created:
            _apply(item, data)
            item.save()
            _save_episodes(item, data.get("episodes", []))
    store_cover(item)
    return item


def refresh_item(item):
    """Fetch the latest details again, e.g. new episodes of a running series. Raises ProviderError."""
    if item.is_manual:
        return item
    data = providers.fetch(item.source, item.media_type, item.source_id)
    old_cover = item.cover_url
    _apply(item, data)
    item.save()
    _save_episodes(item, data.get("episodes", []))
    if item.cover_url != old_cover:
        item.cover = None
        item.save(update_fields=["cover"])
        store_cover(item)
    return item


def store_cover(item):
    """Keep a copy of the cover, so it's served by liveaux. Failing is fine: the item works without one."""
    if item.cover or not item.cover_url:
        return
    try:
        item.cover, item.cover_type = providers.fetch_cover(item.cover_url)
    except providers.ProviderError as error:
        log.info("No cover for %s: %s", item, error)
        return
    item.save(update_fields=["cover", "cover_type"])


def track(user, item, status=Status.PLANNING):
    """The user's entry for the item, made if it isn't there yet."""
    entry, _ = Entry.objects.get_or_create(user=user, item=item, defaults={"status": status})
    return entry


def _start(entry, today):
    if entry.status in (Status.PLANNING, Status.PAUSED, Status.DROPPED):
        entry.status = Status.IN_PROGRESS
    if not entry.started_on:
        entry.started_on = today


def _finish(entry, today):
    entry.status = Status.COMPLETED
    entry.finished_on = today
    if not entry.started_on:
        entry.started_on = today


def check_in(user, item, *, episode=None, when=None, minutes=None, via=Play.Via.MANUAL, note=""):
    """Log one viewing, reading, listening or session, and move the entry along. Returns the play."""
    when = when or timezone.now()
    today = timezone.localdate(when)
    entry = track(user, item, Status.IN_PROGRESS)
    if minutes is None:
        minutes = (episode.runtime if episode else None) or item.runtime
    play = Play.objects.create(
        user=user, item=item, episode=episode, played_at=when, minutes=minutes, via=via, note=note[:280]
    )

    behaviour = item.behaviour
    if behaviour == "single":
        if entry.status == Status.COMPLETED:
            entry.repeats += 1
        entry.progress = item.total or 1
        _finish(entry, today)
    elif behaviour == "episodic":
        _start(entry, today)
        if episode is not None:
            entry.progress = (
                Play.objects.filter(user=user, item=item, episode__isnull=False).values("episode").distinct().count()
            )
        else:
            entry.progress += 1
        if item.total and entry.progress >= item.total and not _still_airing(item):
            _finish(entry, today)
    else:  # sessions
        _start(entry, today)
        entry.progress += 1
    entry.save()
    return play


def _still_airing(item):
    """A series that has more episodes coming isn't finished when you're caught up."""
    if item.media_type not in (MediaType.TV, MediaType.ANIME):
        return False
    status = item.status_text.lower()
    return status in ("returning series", "in production", "releasing") or item.episodes.filter(
        Q(air_date__gt=timezone.localdate()) | Q(air_date__isnull=True)
    ).exists()


def check_in_season(user, item, season):
    """Mark every aired episode of a season that isn't watched yet as watched."""
    watched = set(Play.objects.filter(user=user, item=item, episode__season=season).values_list("episode", flat=True))
    plays = []
    for episode in item.episodes.filter(season=season, air_date__lte=timezone.localdate()):
        if episode.pk not in watched:
            plays.append(check_in(user, item, episode=episode))
    return plays


def undo_play(play):
    """Delete a check-in and take it back out of the progress."""
    entry = Entry.objects.filter(user=play.user, item=play.item).first()
    play.delete()
    if entry is None:
        return
    if play.item.behaviour == "episodic" and play.episode_id:
        entry.progress = (
            Play.objects.filter(user=play.user, item=play.item, episode__isnull=False)
            .values("episode")
            .distinct()
            .count()
        )
    elif play.item.behaviour == "single":
        if entry.repeats:
            entry.repeats -= 1
        elif not Play.objects.filter(user=play.user, item=play.item).exists():
            entry.status, entry.progress, entry.finished_on = Status.PLANNING, 0, None
    elif entry.progress:
        entry.progress -= 1
    if entry.status == Status.COMPLETED and entry.item.total and entry.progress < entry.item.total:
        entry.status = Status.IN_PROGRESS
    entry.save()


def next_episode(user, item):
    """The first aired episode the user hasn't seen, or None."""
    seen = Play.objects.filter(user=user, item=item, episode__isnull=False).values("episode")
    return item.episodes.exclude(pk__in=seen).filter(air_date__lte=timezone.localdate()).first()


def up_next(user):
    """In-progress series with the next episode and what's left. Newest activity first."""
    rows = []
    entries = (
        user.library_entries.filter(status=Status.IN_PROGRESS, item__media_type=MediaType.TV)
        .select_related("item")
        .order_by("-updated_at")
    )
    for entry in entries:
        episode = next_episode(user, entry.item)
        if episode is None:
            continue
        seen = Play.objects.filter(user=user, item=entry.item, episode__isnull=False).values("episode")
        left = entry.item.episodes.exclude(pk__in=seen).filter(air_date__lte=timezone.localdate())
        count = left.count()
        minutes = sum((e.runtime or entry.item.runtime or 0) for e in left)
        rows.append({"entry": entry, "item": entry.item, "episode": episode, "left": count, "minutes": minutes})
    return rows


def calendar(user, start, end):
    """Days from start to end (dates) with what's coming: new episodes, releases and saved events.

    Returns a sorted list of (date, [{"kind", "title", "detail", "url", "time"}]).
    """
    days = {}

    def add(day, row):
        days.setdefault(day, []).append(row)

    tracked = user.library_entries.exclude(status=Status.DROPPED)
    for episode in (
        Episode.objects.filter(item__entries__in=tracked, air_date__gte=start, air_date__lte=end)
        .select_related("item")
        .distinct()
    ):
        add(
            episode.air_date,
            {
                "kind": "episode",
                "label": "New episode",
                "title": episode.item.title,
                "detail": f"{episode.code}{' · ' + episode.title if episode.title else ''}",
                "url": episode.item.get_absolute_url(),
                "uid": f"episode-{episode.pk}",
            },
        )
    for item in Item.objects.filter(entries__in=tracked, release_date__gte=start, release_date__lte=end).exclude(
        media_type=MediaType.TV
    ):
        add(
            item.release_date,
            {
                "kind": "release",
                "label": "Release",
                "title": item.title,
                "detail": item.get_media_type_display(),
                "url": item.get_absolute_url(),
                "uid": f"item-{item.pk}",
            },
        )

    from events.models import Event

    window_start = timezone.make_aware(datetime.combine(start, time.min))
    window_end = timezone.make_aware(datetime.combine(end + timedelta(days=1), time.min))
    for event in (
        Event.objects.overlapping(window_start, window_end)
        .filter(saved_by=user)
        .select_related("venue", "category")
        .distinct()
    ):
        day = max(timezone.localdate(event.starts_at), start)
        add(
            day,
            {
                "kind": "event",
                "label": event.category.name,
                "title": event.title,
                "detail": f"{event.venue.name} · {timezone.localtime(event.starts_at):%H:%M}"
                if not event.is_multi_day
                else f"{event.venue.name} · until {timezone.localtime(event.ends_at):%-d %b}",
                "url": event.get_absolute_url(),
                "uid": f"event-{event.pk}",
                "event": event,
            },
        )
    return sorted(days.items())

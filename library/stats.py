"""Numbers for the stats page: time spent, when, on what, and streaks. Covers going out (the log) too."""

import calendar
from collections import Counter, defaultdict
from datetime import timedelta

from django.utils import timezone

from .models import MEDIA, MediaType, Status


def _bars(counter, keys, labels):
    top = max((counter[k] for k in keys), default=0)
    return [
        {"label": label, "count": counter[k], "percent": round(100 * counter[k] / top) if top else 0}
        for k, label in zip(keys, labels)
    ]


def streaks(days):
    """(current, longest) runs of consecutive days in a set of dates. Current counts up to today or yesterday."""
    longest = run = 0
    previous = None
    for day in sorted(days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    today = timezone.localdate()
    current = 0
    day = today if today in days else today - timedelta(days=1)
    while day in days:
        current += 1
        day -= timedelta(days=1)
    return current, longest


def hours(minutes):
    return round(minutes / 60, 1) if minutes else 0


def compute(user, year=None):
    plays = list(user.plays.select_related("item", "episode"))
    log_entries = list(user.log_entries.select_related("event__category"))
    for play in plays:
        play.local = timezone.localtime(play.played_at)
    for entry in log_entries:
        entry.local = timezone.localtime(entry.event.starts_at)

    years = sorted({p.local.year for p in plays} | {e.local.year for e in log_entries}, reverse=True)
    if year:
        plays = [p for p in plays if p.local.year == year]
        log_entries = [e for e in log_entries if e.local.year == year]

    minutes_by_type = Counter()
    plays_by_type = Counter()
    for play in plays:
        minutes_by_type[play.item.media_type] += play.minutes or 0
        plays_by_type[play.item.media_type] += 1
    types = [t for t in MediaType if plays_by_type[t]]
    top_minutes = max(minutes_by_type.values(), default=0)
    top_plays = max(plays_by_type.values(), default=0)
    by_type = [
        {
            "type": t,
            "label": MEDIA[t]["plural"],
            "plays": plays_by_type[t],
            "hours": hours(minutes_by_type[t]),
            # Bars follow time where there is any, otherwise the number of check-ins.
            "percent": round(100 * minutes_by_type[t] / top_minutes)
            if top_minutes
            else round(100 * plays_by_type[t] / top_plays),
        }
        for t in sorted(types, key=lambda t: (-minutes_by_type[t], -plays_by_type[t]))
    ]

    moments = [p.local for p in plays] + [e.local for e in log_entries]
    weekdays = Counter(m.weekday() for m in moments)
    hours_of_day = Counter(m.hour for m in moments)
    active_days = {m.date() for m in moments}
    current, longest = streaks(active_days)

    entries = user.library_entries.select_related("item")
    completed = [
        e for e in entries if e.status == Status.COMPLETED and (not year or (e.finished_on and e.finished_on.year == year))
    ]
    genres = Counter(g for p in plays for g in p.item.genres)
    creators = Counter(
        name.strip() for p in plays if p.episode_id is None for name in p.item.creator.split(",") if name.strip()
    )
    items_seen = {p.item for p in plays}

    months = Counter(m.month for m in moments)
    per_year = defaultdict(lambda: {"plays": 0, "minutes": 0, "events": 0})
    for play in user.plays.select_related("item"):
        row = per_year[timezone.localtime(play.played_at).year]
        row["plays"] += 1
        row["minutes"] += play.minutes or 0
    for entry in user.log_entries.select_related("event"):
        per_year[timezone.localtime(entry.event.starts_at).year]["events"] += 1

    return {
        "year": year,
        "years": years,
        "play_count": len(plays),
        "hours": hours(sum(p.minutes or 0 for p in plays)),
        "titles": len(items_seen),
        "completed": len(completed),
        "events": len(log_entries),
        "venues": len({e.event.venue_id for e in log_entries}),
        "current_streak": current,
        "longest_streak": longest,
        "active_days": len(active_days),
        "by_type": by_type,
        "weekdays": _bars(weekdays, range(7), [calendar.day_abbr[d] for d in range(7)]),
        "hours_of_day": _bars(hours_of_day, range(24), [f"{h:02d}" for h in range(24)]),
        "months": _bars(months, range(1, 13), [calendar.month_abbr[m] for m in range(1, 13)]) if year else [],
        "top_genres": genres.most_common(8),
        "top_creators": creators.most_common(8),
        "out_categories": Counter(e.event.category.name for e in log_entries).most_common(),
        "best": sorted((e for e in completed if e.score), key=lambda e: (-e.score, e.item.title))[:8],
        "per_year": [
            {"year": y, **row, "hours": hours(row["minutes"])} for y, row in sorted(per_year.items(), reverse=True)
        ],
    }

"""Bring a library in from a CSV file, and take it out again.

Recognised by their columns:
- liveaux's own export
- Letterboxd (diary.csv, watched.csv, ratings.csv)
- Goodreads (library export)
- IMDb (ratings or a list)

Everything is matched without calling outside services, so a big file imports at once. Rows that match
nothing liveaux knows become items added by hand; open one and use *Find details* to link it to its source.
"""

import csv
import io
from datetime import datetime, time

from django.db import transaction
from django.utils import timezone

from .models import Entry, Item, MediaType, Play, Source, Status

EXPORT_COLUMNS = [
    "media_type",
    "source",
    "source_id",
    "title",
    "year",
    "creator",
    "status",
    "score",
    "progress",
    "repeats",
    "started_on",
    "finished_on",
    "notes",
]


class ImportFailed(Exception):
    pass


def export_csv(user):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for e in user.library_entries.select_related("item").order_by("item__media_type", "item__title"):
        writer.writerow(
            {
                "media_type": e.item.media_type,
                "source": e.item.source,
                "source_id": e.item.source_id,
                "title": e.item.title,
                "year": e.item.year or "",
                "creator": e.item.creator,
                "status": e.status,
                "score": e.score or "",
                "progress": e.progress,
                "repeats": e.repeats,
                "started_on": e.started_on or "",
                "finished_on": e.finished_on or "",
                "notes": e.notes,
            }
        )
    return out.getvalue()


def _int(value):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _day(value):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _score_from_stars(stars, out_of=5):
    """Letterboxd and Goodreads stars to liveaux's 1–10."""
    try:
        value = float(stars)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(1, min(10, round(value * 10 / out_of)))


class Importer:
    def __init__(self, user):
        self.user = user
        self.created = self.updated = self.plays = 0

    def item(self, media_type, title, year=None, creator="", source=Source.MANUAL, source_id="", total=None):
        title = (title or "").strip()[:300]
        if not title:
            return None
        if source != Source.MANUAL and source_id:
            found = Item.objects.filter(source=source, media_type=media_type, source_id=source_id).first()
            if found:
                return found
        # Something with the same title and year that liveaux already knows.
        found = Item.objects.filter(media_type=media_type, title__iexact=title, year=year).exclude(source=Source.MANUAL)
        if found.exists():
            return found.first()
        mine = Item.objects.filter(
            media_type=media_type, title__iexact=title, year=year, source=Source.MANUAL, created_by=self.user
        ).first()
        if mine:
            return mine
        return Item.objects.create(
            media_type=media_type,
            title=title,
            year=year,
            creator=creator[:300],
            total=total,
            created_by=self.user,
        )

    def entry(self, item, *, status=None, score=None, progress=None, started=None, finished=None, notes="", repeats=None):
        entry, created = Entry.objects.get_or_create(user=self.user, item=item)
        if created:
            self.created += 1
        else:
            self.updated += 1
        if status:
            # Don't move something back: a row saying "to read" doesn't undo "completed".
            order = [Status.PLANNING, Status.PAUSED, Status.DROPPED, Status.IN_PROGRESS, Status.COMPLETED]
            if created or order.index(status) >= order.index(entry.status):
                entry.status = status
        if score:
            entry.score = score
        if progress is not None:
            entry.progress = max(entry.progress, progress)
        if started and not entry.started_on:
            entry.started_on = started
        if finished and (not entry.finished_on or finished > entry.finished_on):
            entry.finished_on = finished
        if repeats is not None:
            entry.repeats = max(entry.repeats, repeats)
        if notes and notes not in entry.notes:
            entry.notes = f"{entry.notes}\n\n{notes}".strip()
        entry.save()
        return entry

    def play(self, item, day):
        when = timezone.make_aware(datetime.combine(day, time(20, 0)))
        exists = Play.objects.filter(user=self.user, item=item, played_at__date=day, via=Play.Via.IMPORT).exists()
        if not exists:
            Play.objects.create(user=self.user, item=item, played_at=when, minutes=item.runtime, via=Play.Via.IMPORT)
            self.plays += 1

    # Formats

    def liveaux(self, rows):
        valid_types = set(MediaType.values)
        valid_status = set(Status.values)
        for row in rows:
            media_type = row.get("media_type", "")
            if media_type not in valid_types:
                continue
            source = row.get("source") if row.get("source") in Source.values else Source.MANUAL
            item = self.item(
                media_type, row.get("title"), _int(row.get("year")), row.get("creator", ""), source, row.get("source_id", "")
            )
            if item is None:
                continue
            score = _int(row.get("score"))
            self.entry(
                item,
                status=row.get("status") if row.get("status") in valid_status else None,
                score=score if score and 1 <= score <= 10 else None,
                progress=_int(row.get("progress")),
                started=_day(row.get("started_on")),
                finished=_day(row.get("finished_on")),
                notes=row.get("notes", ""),
                repeats=_int(row.get("repeats")),
            )

    def letterboxd(self, rows):
        for row in rows:
            item = self.item(MediaType.MOVIE, row.get("Name"), _int(row.get("Year")))
            if item is None:
                continue
            watched = _day(row.get("Watched Date"))
            self.entry(
                item,
                status=Status.COMPLETED,
                score=_score_from_stars(row.get("Rating")),
                progress=1,
                finished=watched or _day(row.get("Date")),
                notes=row.get("Review", ""),
            )
            if watched:
                self.play(item, watched)

    def goodreads(self, rows):
        shelves = {"read": Status.COMPLETED, "currently-reading": Status.IN_PROGRESS, "to-read": Status.PLANNING}
        for row in rows:
            year = _int(row.get("Original Publication Year")) or _int(row.get("Year Published"))
            pages = _int(row.get("Number of Pages"))
            item = self.item(MediaType.BOOK, row.get("Title"), year, row.get("Author", ""), total=pages)
            if item is None:
                continue
            status = shelves.get(row.get("Exclusive Shelf", ""), Status.PLANNING)
            read = _day(row.get("Date Read"))
            self.entry(
                item,
                status=status,
                score=_score_from_stars(row.get("My Rating")),
                progress=pages if status == Status.COMPLETED and pages else None,
                finished=read,
                notes=row.get("My Review", ""),
            )
            if read:
                self.play(item, read)

    def imdb(self, rows):
        kinds = {
            "movie": MediaType.MOVIE,
            "tvmovie": MediaType.MOVIE,
            "short": MediaType.MOVIE,
            "video": MediaType.MOVIE,
            "tvseries": MediaType.TV,
            "tvminiseries": MediaType.TV,
            "videogame": MediaType.GAME,
        }
        for row in rows:
            media_type = kinds.get((row.get("Title Type") or "").replace(" ", "").lower())
            if media_type is None:
                continue
            item = self.item(media_type, row.get("Title"), _int(row.get("Year")), row.get("Directors", ""))
            if item is None:
                continue
            if not item.runtime and _int(row.get("Runtime (mins)")) and media_type == MediaType.MOVIE:
                item.runtime = _int(row.get("Runtime (mins)"))
                item.save(update_fields=["runtime"])
            score = _int(row.get("Your Rating"))
            rated = _day(row.get("Date Rated"))
            if score:
                self.entry(
                    item,
                    status=Status.COMPLETED,
                    score=score,
                    progress=1 if media_type == MediaType.MOVIE else None,
                    finished=rated,
                )
            else:
                self.entry(item, status=Status.PLANNING)


def detect(headers):
    headers = set(headers)
    if {"media_type", "title", "status"} <= headers:
        return "liveaux"
    if {"Name", "Year", "Letterboxd URI"} <= headers:
        return "letterboxd"
    if {"Title", "Author", "Exclusive Shelf"} <= headers:
        return "goodreads"
    if {"Const", "Title Type", "Title"} <= headers:
        return "imdb"
    return None


FORMAT_NAMES = {"liveaux": "liveaux", "letterboxd": "Letterboxd", "goodreads": "Goodreads", "imdb": "IMDb"}


def import_csv(user, uploaded):
    """Import an uploaded CSV file. Returns (format name, importer) or raises ImportFailed."""
    raw = uploaded.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    fmt = detect(reader.fieldnames or [])
    if fmt is None:
        raise ImportFailed(
            "liveaux doesn't recognise this file. Use an export from liveaux, Letterboxd, Goodreads or IMDb."
        )
    importer = Importer(user)
    with transaction.atomic():
        getattr(importer, fmt)(reader)
    return FORMAT_NAMES[fmt], importer


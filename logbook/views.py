import calendar
from collections import Counter

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from events.models import Event

from .forms import LogEntryForm
from .models import LogEntry


def _entries(user):
    """The user's log entries, each with `year`: the local year of the show."""
    entries = list(user.log_entries.select_related("event__venue__city").prefetch_related("event__artists"))
    for entry in entries:
        entry.year = timezone.localtime(entry.event.starts_at).year
    return entries


def _years(entries):
    """Years with at least one logged show, newest first."""
    return sorted({e.year for e in entries}, reverse=True)


@require_POST
@login_required
def attended(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if not event.has_started:
        messages.error(request, "You can log a show once it has started.")
        return redirect(event)
    entry, created = LogEntry.objects.get_or_create(user=request.user, event=event)
    if created:
        messages.success(request, f"{event.title} is in your log. Add a rating or a note if you like.")
    return redirect(entry.get_edit_url())


@login_required
def edit(request, pk):
    entry = get_object_or_404(LogEntry.objects.select_related("event__venue"), pk=pk, user=request.user)
    form = LogEntryForm(request.POST or None, instance=entry)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect("logbook:mine")
    return render(request, "logbook/entry_form.html", {"form": form, "entry": entry})


@require_POST
@login_required
def delete(request, pk):
    entry = get_object_or_404(LogEntry, pk=pk, user=request.user)
    entry.delete()
    messages.success(request, f"{entry.event.title} is removed from your log.")
    return redirect("logbook:mine")


def _log_page(request, owner, is_own):
    entries = _entries(owner)
    return render(
        request,
        "logbook/log.html",
        {"owner": owner, "entries": entries, "years": _years(entries), "is_own": is_own},
    )


@login_required
def mine(request):
    return _log_page(request, request.user, is_own=True)


def _public_owner(pk):
    owner = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    if not owner.log_is_public:
        raise Http404
    return owner


def public(request, pk):
    owner = _public_owner(pk)
    if owner == request.user:
        return redirect("logbook:mine")
    return _log_page(request, owner, is_own=False)


def year_stats(entries):
    """Numbers for a year overview. `entries` are LogEntry objects from one year."""
    venues = Counter(e.event.venue for e in entries)
    cities = Counter(e.event.venue.city for e in entries)
    artists = Counter(artist for e in entries for artist in e.event.artists.all())
    ratings = [e.rating for e in entries if e.rating]
    months = Counter(timezone.localtime(e.event.starts_at).month for e in entries)
    busiest = max(months.values(), default=0)
    return {
        "count": len(entries),
        "venue_count": len(venues),
        "city_count": len(cities),
        "top_venues": venues.most_common(5),
        "top_artists": artists.most_common(5),
        "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        "best": sorted((e for e in entries if e.rating), key=lambda e: (-e.rating, e.event.starts_at))[:5],
        "months": [
            {
                "number": m,
                "name": calendar.month_abbr[m],
                "count": months[m],
                "percent": round(100 * months[m] / busiest) if busiest else 0,
            }
            for m in range(1, 13)
        ],
        "first": min(entries, key=lambda e: e.event.starts_at, default=None),
        "latest": max(entries, key=lambda e: e.event.starts_at, default=None),
    }


def _year_page(request, owner, year, is_own):
    all_entries = _entries(owner)
    entries = [e for e in all_entries if e.year == year]
    if not entries and not is_own:
        raise Http404
    return render(
        request,
        "logbook/year.html",
        {
            "owner": owner,
            "year": year,
            "years": _years(all_entries),
            "entries": sorted(entries, key=lambda e: e.event.starts_at),
            "stats": year_stats(entries),
            "is_own": is_own,
        },
    )


@login_required
def my_year(request, year):
    return _year_page(request, request.user, year, is_own=True)


def public_year(request, pk, year):
    owner = _public_owner(pk)
    return _year_page(request, owner, year, is_own=owner == request.user)

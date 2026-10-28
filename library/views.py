import random
from datetime import timedelta
from itertools import groupby

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import ical, imports, providers, ratings, services
from . import stats as library_stats
from .forms import CheckInForm, CopyForm, EntryForm, ImportForm, ListForm, ManualItemForm
from .models import MEDIA, Copy, Entry, Item, ListItem, MediaList, MediaType, Play, Source, Status

SORTS = {
    "recent": ("Recently updated", ["-updated_at"]),
    "score": ("Score", ["-score", "item__title"]),
    "title": ("Title", ["item__title"]),
    "year": ("Year", ["-item__year", "item__title"]),
}


def _chips(request, param, options, all_label=None):
    """Filter links that change one query parameter and keep the others."""
    current = request.GET.get(param, "")

    def href(value):
        query = request.GET.copy()
        query.pop(param, None)
        if value:
            query[param] = value
        return f"?{query.urlencode()}" if query else request.path

    chips = [{"label": all_label, "href": href(""), "active": not current}] if all_label else []
    chips += [{"label": label, "href": href(value), "active": value == current} for value, label in options]
    return chips


def _type_options():
    return [(t.value, MEDIA[t]["plural"]) for t in MediaType]


def _back(request, default):
    """Redirect to the page the form came from when it's on this site, else to `default`."""
    target = request.POST.get("next", "")
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(default)


def _visible_item(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if not item.visible_to(request.user):
        raise Http404
    return item


# The library


@login_required
def index(request):
    user = request.user
    entries = user.library_entries.select_related("item")
    today = timezone.localdate()
    return render(
        request,
        "library/index.html",
        {
            "up_next": services.up_next(user)[:8],
            "in_progress": entries.filter(status=Status.IN_PROGRESS).exclude(item__media_type=MediaType.TV)[:12],
            "planning": entries.filter(status=Status.PLANNING)[:12],
            "recently_finished": entries.filter(status=Status.COMPLETED).order_by("-finished_on", "-updated_at")[:12],
            "coming": services.calendar(user, today, today + timedelta(days=14))[:6],
            "counts": {
                row["item__media_type"]: row["n"]
                for row in entries.values("item__media_type").annotate(n=Count("id"))
            },
            "total": entries.count(),
            "type_chips": [
                {"label": MEDIA[t]["plural"], "href": f"{reverse('library:browse')}?type={t.value}", "active": False}
                for t in MediaType
            ],
        },
    )


@login_required
def browse(request):
    entries = request.user.library_entries.select_related("item")
    media_type = request.GET.get("type", "")
    if media_type in MediaType.values:
        entries = entries.filter(item__media_type=media_type)
    status = request.GET.get("status", "")
    if status in Status.values:
        entries = entries.filter(status=status)
    query = request.GET.get("q", "").strip()
    if query:
        entries = entries.filter(Q(item__title__icontains=query) | Q(item__creator__icontains=query))
    sort = request.GET.get("sort", "recent")
    entries = entries.order_by(*SORTS.get(sort, SORTS["recent"])[1])
    return render(
        request,
        "library/browse.html",
        {
            "entries": entries,
            "query": query,
            "heading": MEDIA[media_type]["plural"] if media_type in MediaType.values else "Everything",
            "type_chips": _chips(request, "type", _type_options(), "Everything"),
            "status_chips": _chips(request, "status", Status.choices, "Any status"),
            "sort_chips": _chips(request, "sort", [(k, v[0]) for k, v in SORTS.items() if k != "recent"], "Recent"),
        },
    )


@login_required
def search(request):
    media_type = request.GET.get("type", MediaType.MOVIE)
    if media_type not in MediaType.values:
        media_type = MediaType.MOVIE
    query = request.GET.get("q", "").strip()
    source = providers.source_for(media_type)
    results, error = [], None
    if query and source:
        try:
            results = providers.search(media_type, query)
        except providers.ProviderError:
            error = "The source didn't answer. Try again in a moment, or add it by hand."
    known = {
        (i.source, i.source_id): i
        for i in Item.objects.filter(
            media_type=media_type, source=source, source_id__in=[r["source_id"] for r in results]
        )
    }
    mine = set(request.user.library_entries.filter(item__in=known.values()).values_list("item_id", flat=True))
    for r in results:
        item = known.get((r["source"], r["source_id"]))
        r["item"] = item
        r["in_library"] = item is not None and item.pk in mine
        r["cover"] = proxied_cover(r["cover_url"])
        r["source_label"] = Source(r["source"]).label
    return render(
        request,
        "library/search.html",
        {
            "query": query,
            "media_type": media_type,
            "media_label": MEDIA[media_type]["plural"].lower(),
            "source": source,
            "source_label": Source(source).label if source else None,
            "results": results,
            "error": error,
            "type_chips": [
                {"label": label, "href": f"?type={value}&q={query}" if query else f"?type={value}", "active": value == media_type}
                for value, label in _type_options()
            ],
        },
    )


@require_POST
@login_required
def add(request):
    source = request.POST.get("source", "")
    media_type = request.POST.get("media_type", "")
    source_id = request.POST.get("source_id", "").strip()
    status = request.POST.get("status", Status.PLANNING)
    if source not in providers.PROVIDERS or media_type not in MediaType.values or not source_id:
        raise Http404
    if status not in Status.values:
        status = Status.PLANNING
    try:
        item = services.get_or_create_item(source, media_type, source_id)
    except providers.ProviderError:
        messages.error(request, "Couldn't get the details just now. Try again in a moment.")
        return redirect(request.META.get("HTTP_REFERER") or "library:search")
    entry = services.track(request.user, item, status)
    messages.success(request, f"{item.title} is in your library under {entry.get_status_display().lower()}.")
    return redirect(item)


@login_required
def add_manual(request):
    initial = {"media_type": request.GET.get("type"), "title": request.GET.get("q", "")}
    form = ManualItemForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.source = Source.MANUAL
        item.created_by = request.user
        item.save()
        services.track(request.user, item)
        messages.success(request, f"{item.title} is in your library.")
        return redirect(item)
    return render(request, "library/item_form.html", {"form": form})


@login_required
def edit_manual(request, pk):
    item = get_object_or_404(Item, pk=pk, source=Source.MANUAL, created_by=request.user)
    form = ManualItemForm(request.POST or None, instance=item)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect(item)
    return render(request, "library/item_form.html", {"form": form, "item": item})


def _seasons(user, item):
    """Episodes per season, each marked with how often the user watched it."""
    watched = {}
    for play in Play.objects.filter(user=user, item=item, episode__isnull=False).values("episode"):
        watched[play["episode"]] = watched.get(play["episode"], 0) + 1
    today = timezone.localdate()
    seasons = []
    for number, episodes in groupby(item.episodes.all(), key=lambda e: e.season):
        episodes = list(episodes)
        for e in episodes:
            e.times = watched.get(e.pk, 0)
            e.aired = e.air_date is not None and e.air_date <= today
        aired = [e for e in episodes if e.aired]
        seasons.append(
            {
                "number": number,
                "episodes": episodes,
                "seen": sum(1 for e in episodes if e.times),
                "aired": len(aired),
                "complete": bool(aired) and all(e.times for e in aired),
            }
        )
    return seasons


@login_required
def item_detail(request, pk):
    item = _visible_item(request, pk)
    user = request.user
    entry = Entry.objects.filter(user=user, item=item).first()
    plays = item.plays.filter(user=user).select_related("episode")
    lists = user.media_lists.filter(is_smart=False)
    on_lists = set(ListItem.objects.filter(media_list__in=lists, item=item).values_list("media_list_id", flat=True))
    seasons = _seasons(user, item) if item.has_episodes else []
    return render(
        request,
        "library/item_detail.html",
        {
            "item": item,
            "entry": entry,
            "entry_form": EntryForm(instance=entry or Entry(user=user, item=item)),
            "check_in_form": CheckInForm(),
            "plays": plays[:50],
            "play_count": plays.count(),
            "seasons": seasons,
            "next_episode": services.next_episode(user, item) if item.has_episodes else None,
            "lists": [{"list": lst, "on": lst.pk in on_lists} for lst in lists],
            "copies": item.copies.filter(user=user),
            "copy_form": CopyForm(),
            "can_edit": item.is_manual and item.created_by_id == user.pk,
            "others": item.entries.exclude(user=user).count(),
            "today": timezone.localdate(),
            "elsewhere": ratings.summary(item),
        },
    )


@login_required
def elsewhere(request, pk):
    """The Elsewhere block on its own, with fresh scores: the item page swaps it in once it's loaded."""
    item = _visible_item(request, pk)
    ratings.refresh(item)
    response = render(request, "library/_elsewhere.html", {"item": item, "elsewhere": ratings.summary(item)})
    response["Cache-Control"] = "private, no-cache"
    return response


@require_POST
@login_required
def entry_update(request, pk):
    item = _visible_item(request, pk)
    entry = Entry.objects.filter(user=request.user, item=item).first() or Entry(user=request.user, item=item)
    form = EntryForm(request.POST, instance=entry)
    if form.is_valid():
        entry = form.save()
        if entry.status == Status.COMPLETED and not entry.finished_on:
            entry.finished_on = timezone.localdate()
            entry.save(update_fields=["finished_on"])
        messages.success(request, "Saved.")
    else:
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect(item)


@require_POST
@login_required
def entry_remove(request, pk):
    item = _visible_item(request, pk)
    request.user.library_entries.filter(item=item).delete()
    request.user.plays.filter(item=item).delete()
    messages.success(request, f"{item.title} is out of your library, with its history.")
    return redirect("library:index")


@require_POST
@login_required
def check_in(request, pk):
    item = _visible_item(request, pk)
    form = CheckInForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
        return redirect(item)
    episode = None
    if request.POST.get("episode"):
        episode = get_object_or_404(item.episodes, pk=request.POST["episode"])
    services.check_in(
        request.user,
        item,
        episode=episode,
        when=form.cleaned_data["played_at"],
        minutes=form.cleaned_data["minutes"],
        note=form.cleaned_data["note"],
    )
    what = episode.code if episode else item.title
    messages.success(request, f"{item.info['verb']}: {what}.")
    return _back(request, item.get_absolute_url())


@require_POST
@login_required
def check_in_season(request, pk, season):
    item = _visible_item(request, pk)
    plays = services.check_in_season(request.user, item, season)
    messages.success(request, f"Season {season}: {len(plays)} episode{'s' if len(plays) != 1 else ''} checked in.")
    return redirect(item)


@require_POST
@login_required
def play_delete(request, pk):
    play = get_object_or_404(Play, pk=pk, user=request.user)
    item = play.item
    services.undo_play(play)
    messages.success(request, "That check-in is gone.")
    return _back(request, item.get_absolute_url())


@require_POST
@login_required
def refresh(request, pk):
    item = _visible_item(request, pk)
    try:
        services.refresh_item(item)
        ratings.refresh(item, force=True)
        messages.success(request, "Details are up to date.")
    except providers.ProviderError:
        messages.error(request, "Couldn't reach the source. Try again later.")
    return redirect(item)


@login_required
def link(request, pk):
    """Swap an item added by hand for the real thing from a source, keeping the user's entry and history."""
    item = get_object_or_404(Item, pk=pk, source=Source.MANUAL)
    if not item.visible_to(request.user):
        raise Http404
    source = providers.source_for(item.media_type)
    if request.method == "POST" and source:
        try:
            target = services.get_or_create_item(source, item.media_type, request.POST.get("source_id", ""))
        except providers.ProviderError:
            messages.error(request, "Couldn't get the details just now.")
            return redirect("library:link", pk=item.pk)
        _move(request.user, item, target)
        messages.success(request, f"Linked to {target.title}.")
        return redirect(target)
    query = request.GET.get("q", item.title)
    results, error = [], None
    if source:
        try:
            results = providers.search(item.media_type, query)
        except providers.ProviderError:
            error = "The source didn't answer. Try again in a moment."
    for r in results:
        r["cover"] = proxied_cover(r["cover_url"])
        r["source_label"] = Source(r["source"]).label
    return render(
        request,
        "library/link.html",
        {"item": item, "results": results, "query": query, "error": error, "source": source},
    )


@transaction.atomic
def _move(user, old, new):
    old_entry = Entry.objects.filter(user=user, item=old).first()
    if old_entry:
        entry = Entry.objects.filter(user=user, item=new).first()
        if entry is None:
            old_entry.item = new
            old_entry.save()
        else:
            entry.score = entry.score or old_entry.score
            entry.notes = "\n\n".join(n for n in (entry.notes, old_entry.notes) if n)
            entry.progress = max(entry.progress, old_entry.progress)
            entry.started_on = entry.started_on or old_entry.started_on
            entry.finished_on = entry.finished_on or old_entry.finished_on
            if entry.status == Status.PLANNING:
                entry.status = old_entry.status
            entry.save()
            old_entry.delete()
    for play in Play.objects.filter(user=user, item=old).select_related("episode"):
        if play.episode:
            play.episode = new.episodes.filter(season=play.episode.season, number=play.episode.number).first()
        play.item = new
        play.save()
    Copy.objects.filter(user=user, item=old).update(item=new)
    for li in ListItem.objects.filter(media_list__user=user, item=old):
        if ListItem.objects.filter(media_list=li.media_list, item=new).exists():
            li.delete()
        else:
            li.item = new
            li.save()
    if not old.entries.exists() and not old.plays.exists():
        old.delete()


# Covers


def _image(body, content_type):
    response = HttpResponse(body, content_type=content_type or "image/jpeg")
    response["Cache-Control"] = "public, max-age=2592000"
    return response


def cover(request, pk):
    item = get_object_or_404(Item, pk=pk)
    if item.is_manual:
        raise Http404
    if not item.cover:
        services.store_cover(item)
    if not item.cover:
        raise Http404
    return _image(bytes(item.cover), item.cover_type)


def proxied_cover(url):
    """A liveaux address for a cover in search results, so the visitor's browser doesn't load it from elsewhere."""
    if not url or not providers.cover_allowed(url):
        return ""
    return f"{reverse('library:cover_proxy')}?u={signing.dumps(url, salt='cover')}"


@login_required
def cover_proxy(request):
    try:
        url = signing.loads(request.GET.get("u", ""), salt="cover")
    except signing.BadSignature:
        raise Http404
    key = f"cover:{signing.dumps(url, salt='cover-key')[-40:]}"
    cached = cache.get(key)
    if cached is None:
        try:
            cached = providers.fetch_cover(url)
        except providers.ProviderError:
            raise Http404
        cache.set(key, cached, 60 * 60 * 24)
    return _image(*cached)


# Calendar


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        weeks = max(1, min(26, int(request.GET.get("weeks", 6))))
    except ValueError:
        weeks = 6
    days = services.calendar(request.user, today, today + timedelta(weeks=weeks))
    feed = request.build_absolute_uri(reverse("library:calendar_ics", args=[request.user.get_api_token()]))
    return render(request, "library/calendar.html", {"days": days, "weeks": weeks, "feed_url": feed, "today": today})


def _user_by_token(token):
    if not token or len(token) < 20:
        raise Http404
    return get_object_or_404(get_user_model(), api_token=token, is_active=True)


def calendar_ics(request, token):
    user = _user_by_token(token)
    today = timezone.localdate()
    days = services.calendar(user, today - timedelta(days=30), today + timedelta(days=180))
    response = HttpResponse(ical.render(days, host=request.get_host()), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="liveaux.ics"'
    return response


@require_POST
@login_required
def reset_token(request):
    request.user.reset_api_token()
    messages.success(request, "New secret address made. Update your calendar app, media server and scripts.")
    return redirect("library:connect")


@login_required
def connect(request):
    token = request.user.get_api_token()

    def absolute(name, *args):
        return request.build_absolute_uri(reverse(name, args=args))

    return render(
        request,
        "library/connect.html",
        {
            "calendar_url": absolute("library:calendar_ics", token),
            "plex_url": absolute("library:webhook", token, "plex"),
            "jellyfin_url": absolute("library:webhook", token, "jellyfin"),
            "api_url": absolute("library:api_entries"),
            "token": token,
            "tmdb": bool(settings.TMDB_API_KEY),
            "igdb": providers.igdb_configured(),
        },
    )


# Stats, discover, diary


@login_required
def stats_view(request):
    try:
        year = int(request.GET.get("year", "")) or None
    except ValueError:
        year = None
    data = library_stats.compute(request.user, year)
    year_chips = [{"label": "All time", "href": request.path, "active": not year}] + [
        {"label": str(y), "href": f"?year={y}", "active": y == year} for y in data["years"]
    ]
    return render(request, "library/stats.html", {"stats": data, "year_chips": year_chips})


@login_required
def discover(request):
    user = request.user
    mine = set(user.library_entries.values_list("item_id", flat=True))
    rows = []
    if settings.TMDB_API_KEY:
        favourites = (
            user.library_entries.filter(item__source=Source.TMDB, score__gte=7)
            .select_related("item")
            .order_by("-score", "-updated_at")[:3]
        )
        known = {(i.media_type, i.source_id): i.pk for i in Item.objects.filter(source=Source.TMDB, entries__user=user)}
        for entry in favourites:
            key = f"recommendations:{entry.item.media_type}:{entry.item.source_id}"
            results = cache.get(key)
            if results is None:
                try:
                    results = providers.tmdb_recommendations(entry.item.media_type, entry.item.source_id)
                except providers.ProviderError:
                    results = []
                cache.set(key, results, 60 * 60 * 24)
            results = [dict(r, cover=proxied_cover(r["cover_url"])) for r in results if (r["media_type"], r["source_id"]) not in known]
            if results:
                rows.append({"title": f"Because you liked {entry.item.title}", "results": results[:8]})

    popular = (
        Item.objects.exclude(source=Source.MANUAL)
        .exclude(pk__in=mine)
        .annotate(people=Count("entries", distinct=True), best=Max("entries__score"))
        .filter(people__gt=0)
        .order_by("-people", "-best")[:12]
    )
    planning = list(user.library_entries.filter(status=Status.PLANNING).select_related("item"))
    random.shuffle(planning)
    return render(
        request,
        "library/discover.html",
        {"rows": rows, "popular": popular, "planning": planning[:8], "tmdb": bool(settings.TMDB_API_KEY)},
    )


def _diary(owner, year=None):
    """Plays and visits to events, newest first, as (month, rows)."""
    plays = owner.plays.select_related("item", "episode")
    log_entries = owner.log_entries.select_related("event__venue", "event__category")
    if year:
        plays = plays.filter(played_at__year=year)
        log_entries = log_entries.filter(event__starts_at__year=year)
    rows = [{"kind": "play", "when": p.played_at, "play": p} for p in plays[:500]]
    rows += [{"kind": "event", "when": e.event.starts_at, "entry": e} for e in log_entries[:500]]
    rows.sort(key=lambda r: r["when"], reverse=True)
    for row in rows:
        row["local"] = timezone.localtime(row["when"])
    return [(month, list(group)) for month, group in groupby(rows, key=lambda r: r["local"].strftime("%B %Y"))]


@login_required
def diary(request):
    return render(request, "library/diary.html", {"months": _diary(request.user), "is_own": True, "owner": request.user})


def public_library(request, pk):
    owner = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    if not owner.library_is_public:
        raise Http404
    entries = owner.library_entries.select_related("item").exclude(status=Status.DROPPED)
    media_type = request.GET.get("type", "")
    if media_type in MediaType.values:
        entries = entries.filter(item__media_type=media_type)
    return render(
        request,
        "library/public.html",
        {
            "owner": owner,
            "in_progress": entries.filter(status=Status.IN_PROGRESS),
            "completed": entries.filter(status=Status.COMPLETED).order_by("-finished_on", "-updated_at"),
            "lists": owner.media_lists.filter(is_public=True),
            "type_chips": _chips(request, "type", _type_options(), "Everything"),
        },
    )


# Collection


@login_required
def collection(request):
    copies = request.user.copies.select_related("item")
    fmt = request.GET.get("format", "")
    if fmt in Copy.Format.values:
        copies = copies.filter(format=fmt)
    used = request.user.copies.values_list("format", flat=True).distinct()
    options = [(f.value, f.label) for f in Copy.Format if f.value in set(used)]
    return render(
        request,
        "library/collection.html",
        {"copies": copies, "format_chips": _chips(request, "format", options, "All formats")},
    )


@require_POST
@login_required
def copy_add(request, pk):
    item = _visible_item(request, pk)
    form = CopyForm(request.POST)
    if form.is_valid():
        copy = form.save(commit=False)
        copy.user, copy.item = request.user, item
        copy.save()
        messages.success(request, f"{item.title} on {copy.get_format_display()} is in your collection.")
    else:
        messages.error(request, "Pick a format.")
    return redirect(item)


@require_POST
@login_required
def copy_delete(request, pk):
    copy = get_object_or_404(Copy, pk=pk, user=request.user)
    copy.delete()
    messages.success(request, "Removed from your collection.")
    return _back(request, "library:collection")


# Import and export


@login_required
def import_view(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            name, result = imports.import_csv(request.user, form.cleaned_data["file"])
        except imports.ImportFailed as error:
            form.add_error("file", str(error))
        else:
            messages.success(
                request,
                f"{name} import done: {result.created} added, {result.updated} updated, {result.plays} check-ins.",
            )
            return redirect("library:index")
    return render(request, "library/import.html", {"form": form})


@login_required
def export_csv(request):
    response = HttpResponse(imports.export_csv(request.user), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="liveaux-library.csv"'
    return response


# Lists


@login_required
def list_index(request):
    lists = request.user.media_lists.annotate(count=Count("list_items"))
    return render(request, "library/list_index.html", {"lists": lists})


@login_required
def list_create(request):
    form = ListForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        media_list = form.save(commit=False)
        media_list.user = request.user
        form.save()
        messages.success(request, f"List {media_list.name} is made.")
        return redirect(media_list)
    return render(request, "library/list_form.html", {"form": form})


@login_required
def list_edit(request, pk):
    media_list = get_object_or_404(MediaList, pk=pk, user=request.user)
    form = ListForm(request.POST or None, instance=media_list)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect(media_list)
    return render(request, "library/list_form.html", {"form": form, "media_list": media_list})


@require_POST
@login_required
def list_delete(request, pk):
    media_list = get_object_or_404(MediaList, pk=pk, user=request.user)
    media_list.delete()
    messages.success(request, f"List {media_list.name} is deleted.")
    return redirect("library:lists")


def list_detail(request, pk):
    media_list = get_object_or_404(MediaList.objects.select_related("user"), pk=pk)
    if not media_list.visible_to(request.user):
        raise Http404
    is_own = media_list.user_id == request.user.pk
    return render(
        request,
        "library/list_detail.html",
        {
            "media_list": media_list,
            "items": media_list.get_items(),
            "is_own": is_own,
            "feed_url": request.build_absolute_uri(reverse("library:list_feed", args=[media_list.pk])),
        },
    )


@require_POST
@login_required
def list_toggle_item(request, pk, item_pk):
    media_list = get_object_or_404(MediaList, pk=pk, user=request.user, is_smart=False)
    item = _visible_item(request, item_pk)
    existing = ListItem.objects.filter(media_list=media_list, item=item)
    if existing.exists():
        existing.delete()
        messages.success(request, f"{item.title} is off {media_list.name}.")
    else:
        position = (media_list.list_items.aggregate(m=Max("position"))["m"] or 0) + 1
        ListItem.objects.create(media_list=media_list, item=item, position=position)
        messages.success(request, f"{item.title} is on {media_list.name}.")
    media_list.save(update_fields=["updated_at"])
    return _back(request, item.get_absolute_url())

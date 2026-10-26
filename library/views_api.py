"""Machine-facing endpoints: media server webhooks, a small JSON API and RSS feeds for public lists.

They authenticate with the user's secret token (Settings → Connect), not with a session.
"""

import json
from datetime import timedelta

from django.contrib.syndication.views import Feed
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from . import providers, scrobble, services
from .models import Item, MediaList, MediaType, Play, Source, Status
from .views import _user_by_token


@csrf_exempt
@require_POST
def webhook(request, token, service):
    user = _user_by_token(token)
    handler = {"plex": scrobble.plex, "jellyfin": scrobble.jellyfin}.get(service)
    if handler is None:
        raise Http404
    play = handler(user, request)
    return JsonResponse({"logged": play is not None, "play": play.pk if play else None})


def _api_user(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    try:
        return _user_by_token(header.removeprefix("Bearer ").strip())
    except Http404:
        return None


def _unauthorized():
    response = JsonResponse({"error": "Send your token as 'Authorization: Bearer <token>'."}, status=401)
    response["WWW-Authenticate"] = "Bearer"
    return response


def _item_json(item):
    return {
        "id": item.pk,
        "media_type": item.media_type,
        "source": item.source,
        "source_id": item.source_id,
        "title": item.title,
        "year": item.year,
        "creator": item.creator,
        "total": item.total,
    }


@require_GET
def api_entries(request):
    user = _api_user(request)
    if user is None:
        return _unauthorized()
    entries = user.library_entries.select_related("item")
    if request.GET.get("type") in MediaType.values:
        entries = entries.filter(item__media_type=request.GET["type"])
    if request.GET.get("status") in Status.values:
        entries = entries.filter(status=request.GET["status"])
    return JsonResponse(
        {
            "entries": [
                {
                    "item": _item_json(e.item),
                    "status": e.status,
                    "score": e.score,
                    "progress": e.progress,
                    "repeats": e.repeats,
                    "started_on": e.started_on,
                    "finished_on": e.finished_on,
                    "notes": e.notes,
                    "updated_at": e.updated_at,
                }
                for e in entries
            ]
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_plays(request):
    user = _api_user(request)
    if user is None:
        return _unauthorized()
    if request.method == "POST":
        return _api_check_in(request, user)
    plays = user.plays.select_related("item", "episode")
    since = parse_datetime(request.GET.get("since", "") or "")
    if since:
        plays = plays.filter(played_at__gte=since)
    return JsonResponse(
        {
            "plays": [
                {
                    "id": p.pk,
                    "item": _item_json(p.item),
                    "episode": {"season": p.episode.season, "number": p.episode.number} if p.episode else None,
                    "played_at": p.played_at,
                    "minutes": p.minutes,
                    "via": p.via,
                }
                for p in plays[:1000]
            ]
        }
    )


def _api_check_in(request, user):
    """POST {"item": id} or {"media_type", "source", "source_id"} or {"media_type", "title"},
    optionally with "season", "episode", "played_at" (ISO 8601) and "minutes"."""
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "Send JSON."}, status=400)
    item = None
    media_type = data.get("media_type")
    try:
        if data.get("item"):
            item = Item.objects.filter(pk=data["item"]).first()
            if item and not item.visible_to(user):
                item = None
        elif media_type in MediaType.values and data.get("source") in providers.PROVIDERS and data.get("source_id"):
            item = services.get_or_create_item(data["source"], media_type, str(data["source_id"]))
        elif media_type in MediaType.values and data.get("title"):
            item, _ = scrobble.resolve(user, media_type=media_type, title=str(data["title"])[:300], year=data.get("year"))
    except providers.ProviderError:
        return JsonResponse({"error": "The source didn't answer."}, status=502)
    if item is None:
        return JsonResponse({"error": "Couldn't find that item."}, status=400)
    episode = None
    if data.get("season") is not None and data.get("episode") is not None:
        episode = item.episodes.filter(season=data["season"], number=data["episode"]).first()
    played_at = parse_datetime(str(data.get("played_at") or "")) or None
    if played_at and timezone.is_naive(played_at):
        played_at = timezone.make_aware(played_at)
    minutes = data.get("minutes")
    play = services.check_in(
        user,
        item,
        episode=episode,
        when=played_at,
        minutes=int(minutes) if isinstance(minutes, int) and minutes > 0 else None,
        via=Play.Via.API,
    )
    return JsonResponse({"play": play.pk, "item": _item_json(item)}, status=201)


@require_GET
def api_calendar(request):
    user = _api_user(request)
    if user is None:
        return _unauthorized()
    today = timezone.localdate()
    days = services.calendar(user, today, today + timedelta(days=60))
    return JsonResponse(
        {
            "days": [
                {"date": day, "items": [{k: v for k, v in row.items() if k != "event"} for row in rows]}
                for day, rows in days
            ]
        }
    )


class ListFeed(Feed):
    """RSS for a public list: new items show up in a feed reader."""

    def get_object(self, request, pk):
        self.media_list = get_object_or_404(MediaList, pk=pk, is_public=True)
        return self.media_list

    def title(self, obj):
        return f"{obj.name} — liveaux"

    def link(self, obj):
        return obj.get_absolute_url()

    def description(self, obj):
        return obj.description or f"A list by {obj.user.public_name}."

    def items(self, obj):
        return obj.get_items()[:100]

    def item_title(self, item):
        return str(item)

    def item_description(self, item):
        return f"{item.get_media_type_display()}{' by ' + item.creator if item.creator else ''}. {item.description[:400]}"

    def item_link(self, item):
        if item.source != Source.MANUAL and item.url:
            return item.url
        return f"{self.media_list.get_absolute_url()}#item-{item.pk}"


def list_feed(request, pk):
    return ListFeed()(request, pk=pk)


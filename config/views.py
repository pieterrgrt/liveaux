from datetime import timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from events.models import Event
from library import services
from library.models import Status


def home(request):
    """The front page: out in the city, and in at home. Personal when you're logged in."""
    now = timezone.now()
    week = Event.objects.overlapping(now, now + timedelta(days=7)).select_related("venue__city", "category")
    if not request.user.is_authenticated:
        return render(request, "home.html", {"events": week.filter(starts_at__gte=now)[:8], "event_count": week.count()})

    user = request.user
    today = timezone.localdate()
    mine = week.filter(Q(saved_by=user) | Q(venue__followers=user) | Q(promoter__followers=user) | Q(artists__followers=user)).distinct()
    entries = user.library_entries.select_related("item")
    return render(
        request,
        "home.html",
        {
            "my_week": mine[:8],
            "events": week.filter(starts_at__gte=now).exclude(pk__in=mine.values("pk"))[:6],
            "up_next": services.up_next(user)[:6],
            "in_progress": entries.filter(status=Status.IN_PROGRESS).exclude(item__media_type="tv")[:8],
            "coming": services.calendar(user, today, today + timedelta(days=7))[:5],
            "recent_plays": user.plays.select_related("item", "episode")[:5],
            "library_count": entries.count(),
            "to_log": Event.objects.started()
            .filter(saved_by=user, starts_at__gte=now - timedelta(days=14))
            .exclude(log_entries__user=user)
            .select_related("venue")[:3],
        },
    )

from datetime import timedelta

from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone

from events.models import Event
from library import services
from library import views as library_views
from library.models import Status


def _week():
    now = timezone.now()
    return Event.objects.overlapping(now, now + timedelta(days=7)).select_related("venue__city", "category")


def _mine(week, user):
    return week.filter(
        Q(saved_by=user) | Q(venue__followers=user) | Q(promoter__followers=user) | Q(artists__followers=user)
    ).distinct()


def home(request):
    """The front page: the logo, big. You choose live (out in the city) or aux (at home)."""
    week = _week()
    context = {"event_count": week.count()}
    if request.user.is_authenticated:
        user = request.user
        context["saved_count"] = _mine(week, user).count()
        next_up = services.up_next(user)[:1]
        context["next_up"] = next_up[0] if next_up else None
        context["in_progress_count"] = user.library_entries.filter(status=Status.IN_PROGRESS).count()
    return render(request, "home.html", context)


def live(request):
    """Live: out in the city. Your week first when you're logged in, then everything else on."""
    now = timezone.now()
    week = _week()
    upcoming = week.filter(Q(starts_at__gte=now) | Q(ends_at__gte=now))
    context = {"event_count": week.count()}
    if request.user.is_authenticated:
        user = request.user
        mine = _mine(upcoming, user)
        context.update(
            my_week=mine[:12],
            events=upcoming.exclude(pk__in=mine.values("pk"))[:12],
            to_log=Event.objects.started()
            .filter(saved_by=user, starts_at__gte=now - timedelta(days=14))
            .exclude(log_entries__user=user)
            .select_related("venue")[:3],
            recent_log=user.log_entries.select_related("event__venue__city", "event__category")[:4],
        )
    else:
        context["events"] = upcoming[:20]
    return render(request, "live.html", context)


def aux(request):
    """Aux: at home. Your library; without an account, what it is and how to start one."""
    if request.user.is_authenticated:
        return library_views.index(request)
    return render(request, "aux.html")

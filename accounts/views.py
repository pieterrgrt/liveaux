import json

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone

from events.models import Event

from .forms import DeleteAccountForm, ProfileForm


@login_required
def dashboard(request):
    user = request.user
    upcoming = Event.objects.filter(starts_at__gte=timezone.now()).select_related("venue")

    saved = upcoming.filter(saved_by=user)
    from_follows = (
        upcoming.filter(
            Q(venue__followers=user) | Q(promoter__followers=user) | Q(artists__followers=user)
        )
        .exclude(saved_by=user)
        .distinct()[:20]
    )
    # Saved shows that have happened but aren't in the log yet: "were you there?"
    to_log = (
        Event.objects.filter(saved_by=user, starts_at__lt=timezone.now())
        .exclude(log_entries__user=user)
        .select_related("venue")
        .order_by("-starts_at")[:5]
    )
    pages = [
        *user.managed_venues.all(),
        *user.managed_promoters.all(),
        *user.managed_artists.all(),
    ]
    following = [
        *user.followed_venues.all(),
        *user.followed_promoters.all(),
        *user.followed_artists.all(),
    ]
    return render(
        request,
        "accounts/dashboard.html",
        {
            "saved": saved,
            "from_follows": from_follows,
            "to_log": to_log,
            "recent_log": user.log_entries.select_related("event__venue__city")[:5],
            "log_count": user.log_entries.count(),
            "pages": pages,
            "following": following,
            "submissions": user.event_submissions.select_related("venue", "event")[:10],
        },
    )


@login_required
def settings_view(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your settings are saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})


@login_required
def delete_account(request):
    form = DeleteAccountForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        user = request.user
        logout(request)
        user.delete()  # cascades to log entries, memberships, submissions, email addresses
        messages.success(request, "Your account and everything in it is deleted. Take care.")
        return redirect("events:event_list")
    return render(request, "accounts/delete.html", {"form": form})


def _local(dt):
    return timezone.localtime(dt).isoformat() if dt else None


@login_required
def export_data(request):
    """Everything liveaux stores about the user, as a JSON download."""
    user = request.user
    data = {
        "exported_at": _local(timezone.now()),
        "account": {
            "email": user.email,
            "name": user.display_name,
            "log_is_public": user.log_is_public,
            "joined": _local(user.date_joined),
            "last_login": _local(user.last_login),
            "email_addresses": [
                {"email": a.email, "verified": a.verified, "primary": a.primary}
                for a in user.emailaddress_set.all()
            ],
        },
        "log": [
            {
                "event": e.event.title,
                "venue": e.event.venue.name,
                "date": _local(e.event.starts_at),
                "rating": e.rating,
                "note": e.note,
                "logged_at": _local(e.created_at),
            }
            for e in user.log_entries.select_related("event__venue")
        ],
        "saved_events": [
            {"event": e.title, "venue": e.venue.name, "date": _local(e.starts_at)}
            for e in user.saved_events.select_related("venue")
        ],
        "following": {
            "venues": [p.name for p in user.followed_venues.all()],
            "promoters": [p.name for p in user.followed_promoters.all()],
            "artists": [p.name for p in user.followed_artists.all()],
        },
        "manages": {
            "venues": [p.name for p in user.managed_venues.all()],
            "promoters": [p.name for p in user.managed_promoters.all()],
            "artists": [p.name for p in user.managed_artists.all()],
        },
        "event_submissions": [
            {"title": s.title, "venue": s.venue_name, "date": _local(s.starts_at), "status": s.status}
            for s in user.event_submissions.select_related("venue")
        ],
    }
    response = HttpResponse(
        json.dumps(data, indent=2, ensure_ascii=False), content_type="application/json; charset=utf-8"
    )
    response["Content-Disposition"] = 'attachment; filename="liveaux-data.json"'
    return response

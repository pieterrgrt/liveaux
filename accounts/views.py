from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone

from events.models import Event

from .forms import ProfileForm


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
        {"saved": saved, "from_follows": from_follows, "pages": pages, "following": following},
    )


@login_required
def settings_view(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your name is saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})

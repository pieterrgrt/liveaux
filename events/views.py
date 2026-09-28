from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import PAGE_MODELS, Event, Venue


def get_page(kind, pk):
    model = PAGE_MODELS.get(kind)
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=pk)


def event_list(request):
    events = Event.objects.filter(starts_at__gte=timezone.now()).select_related("venue")

    district = request.GET.get("district", "")
    if district:
        events = events.filter(venue__district=district)

    districts = (
        Venue.objects.exclude(district="")
        .order_by("district")
        .values_list("district", flat=True)
        .distinct()
    )
    return render(
        request,
        "events/event_list.html",
        {"events": events, "districts": districts, "current_district": district},
    )


def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("venue", "promoter"), pk=pk)
    more_at_venue = event.venue.upcoming_events().exclude(pk=event.pk)[:3]
    is_saved = request.user.is_authenticated and event.saved_by.filter(pk=request.user.pk).exists()
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "artists": event.artists.all(),
            "more_at_venue": more_at_venue,
            "is_saved": is_saved,
            "can_edit": event.can_edit(request.user),
        },
    )


def page_detail(request, kind, pk):
    page = get_page(kind, pk)
    is_following = request.user.is_authenticated and page.followers.filter(pk=request.user.pk).exists()
    return render(
        request,
        "events/page_detail.html",
        {
            "page": page,
            "events": page.upcoming_events(),
            "is_following": is_following,
            "is_member": page.is_member(request.user),
        },
    )


def _back(request, fallback):
    """Redirect to the page the form was posted from, if it is on this site."""
    next_url = request.POST.get("next", "")
    if next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(fallback)


@require_POST
@login_required
def toggle_save(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.saved_by.filter(pk=request.user.pk).exists():
        event.saved_by.remove(request.user)
    else:
        event.saved_by.add(request.user)
    return _back(request, event)


@require_POST
@login_required
def toggle_follow(request, kind, pk):
    page = get_page(kind, pk)
    if page.followers.filter(pk=request.user.pk).exists():
        page.followers.remove(request.user)
    else:
        page.followers.add(request.user)
    return _back(request, page)

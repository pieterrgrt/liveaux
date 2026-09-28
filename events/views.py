from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Event, Venue


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
    event = get_object_or_404(Event.objects.select_related("venue"), pk=pk)
    more_at_venue = event.venue.events.filter(starts_at__gte=timezone.now()).exclude(pk=event.pk)[:3]
    return render(request, "events/event_detail.html", {"event": event, "more_at_venue": more_at_venue})


def venue_detail(request, pk):
    venue = get_object_or_404(Venue, pk=pk)
    events = venue.events.filter(starts_at__gte=timezone.now())
    return render(request, "events/venue_detail.html", {"venue": venue, "events": events})

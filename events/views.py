from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.mail import mail_admins
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import EventSubmissionForm
from .models import PAGE_MODELS, Category, City, Event, Venue


def get_page(kind, pk):
    model = PAGE_MODELS.get(kind)
    if model is None:
        raise Http404
    return get_object_or_404(model, pk=pk)


def _chips(request, param, options, all_label):
    """Filter links that change one query parameter and keep the others.

    `options` are (value, label) pairs. Returns dicts with label, href and active for the template.
    """
    current = request.GET.get(param, "")

    def href(value):
        query = request.GET.copy()
        query.pop(param, None)
        if value:
            query[param] = value
        if param == "city":
            query.pop("district", None)  # districts belong to a city
        return f"?{query.urlencode()}" if query else request.path

    chips = [{"label": all_label, "href": href(""), "active": not current}]
    chips += [{"label": label, "href": href(value), "active": value == current} for value, label in options]
    return chips


def event_list(request):
    events = Event.objects.on_now_or_later().select_related("venue__city", "category")
    cities = City.objects.all()
    categories = Category.objects.all()

    city = cities.filter(slug=request.GET.get("city", "")).first()
    venues = Venue.objects.all()
    if city:
        events = events.filter(venue__city=city)
        venues = venues.filter(city=city)

    category = categories.filter(slug=request.GET.get("category", "")).first()
    if category:
        events = events.filter(category=category)

    district = request.GET.get("district", "")
    if district:
        events = events.filter(venue__district=district)

    districts = venues.exclude(district="").order_by("district").values_list("district", flat=True).distinct()
    now = timezone.now()
    return render(
        request,
        "events/event_list.html",
        {
            "on_now": events.filter(starts_at__lt=now).order_by("ends_at"),
            "events": events.filter(starts_at__gte=now),
            "current_city": city,
            "current_category": category,
            "current_district": district,
            "city_chips": _chips(request, "city", [(c.slug, c.name) for c in cities], "All cities")
            if len(cities) > 1
            else [],
            "category_chips": _chips(request, "category", [(c.slug, c.name) for c in categories], "Everything"),
            "district_chips": _chips(
                request, "district", [(d, d) for d in districts], f"All of {city.name}" if city else "All districts"
            ),
        },
    )


def this_week(request):
    """/week/ goes to the first city; there is always at least one once venues exist."""
    city = City.objects.first()
    if city is None:
        return redirect("events:event_list")
    return redirect(city)


def city_week(request, slug):
    """What's on in one city from today through the next six days.

    Things that run for days (exhibitions, festivals) are listed once, above the days.
    """
    city = get_object_or_404(City, slug=slug)
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(today, time.min))
    end = start + timedelta(days=7)
    events = (
        Event.objects.overlapping(start, end)
        .filter(venue__city=city)
        .select_related("venue", "category")
        .order_by("starts_at")
    )
    category = Category.objects.filter(slug=request.GET.get("category", "")).first()
    if category:
        events = events.filter(category=category)

    running = []
    days = {today + timedelta(days=n): [] for n in range(7)}
    for event in events:
        if event.is_multi_day:
            running.append(event)
        else:
            days[timezone.localdate(event.starts_at)].append(event)
    return render(
        request,
        "events/city_week.html",
        {
            "city": city,
            "current_category": category,
            "city_links": [
                {"label": c.name, "href": c.get_absolute_url(), "active": c == city} for c in City.objects.all()
            ],
            "category_chips": _chips(
                request, "category", [(c.slug, c.name) for c in Category.objects.all()], "Everything"
            ),
            "running": running,
            "days": [{"date": d, "events": e} for d, e in days.items()],
            "count": len(events),
            "today": today,
            "last_day": today + timedelta(days=6),
        },
    )


def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("venue__city", "promoter", "category"), pk=pk)
    more_at_venue = event.venue.upcoming_events().exclude(pk=event.pk)[:3]
    user = request.user
    is_saved = user.is_authenticated and event.saved_by.filter(pk=user.pk).exists()
    log_entry = event.log_entries.filter(user=user).first() if user.is_authenticated else None
    return render(
        request,
        "events/event_detail.html",
        {
            "event": event,
            "artists": event.artists.all(),
            "more_at_venue": more_at_venue,
            "is_saved": is_saved,
            "log_entry": log_entry,
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


@login_required
def submit_event(request):
    form = EventSubmissionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        submission = form.save(commit=False)
        submission.submitted_by = request.user
        submission.save()
        mail_admins(
            f"New event to review: {submission.title}",
            f"{request.user.email} ({submission.relation}) submitted {submission.title} "
            f"at {submission.venue_name} on {timezone.localtime(submission.starts_at):%d-%m-%Y %H:%M}.\n\n"
            f"Review it in the admin: {request.build_absolute_uri('/admin/events/eventsubmission/')}",
            fail_silently=True,
        )
        messages.success(request, "Thanks! We'll check your event and publish it soon. You can follow its status here.")
        return redirect("accounts:dashboard")
    return render(request, "events/submit.html", {"form": form})

"""Pages for people who manage a venue, promoter or artist."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AddMemberForm, EventForm, page_form_class
from .models import PAGE_MODELS, Event, Membership
from .views import get_page

# Venues are real places: access is granted by an admin, not self-service.
SELF_SERVICE_KINDS = ("promoter", "artist")
EVENT_KINDS = ("venue", "promoter")


def _member_page(request, kind, pk, owner=False):
    """The page, if the current user may manage it (or own it, when owner=True)."""
    page = get_page(kind, pk)
    membership = page.membership_for(request.user)
    if request.user.is_superuser:
        return page, membership
    if membership is None or (owner and not membership.is_owner):
        raise PermissionDenied
    return page, membership


@login_required
def create_page(request, kind):
    if kind not in SELF_SERVICE_KINDS:
        raise Http404
    model = PAGE_MODELS[kind]
    form = page_form_class(model)(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            page = form.save()
            page.memberships.create(user=request.user, role=Membership.OWNER)
        messages.success(request, f"{page.name} is live. You are its owner.")
        return redirect(page.get_manage_url())
    return render(
        request, "events/manage/page_form.html", {"form": form, "kind_label": model.kind_label, "page": None}
    )


@login_required
def manage_page(request, kind, pk):
    page, membership = _member_page(request, kind, pk)
    events = page.events.select_related("venue").order_by("starts_at")
    return render(
        request,
        "events/manage/page.html",
        {
            "page": page,
            "membership": membership,
            "is_owner": request.user.is_superuser or (membership and membership.is_owner),
            "can_add_events": kind in EVENT_KINDS,
            "upcoming": events.on_now_or_later(),
            "past": events.exclude(pk__in=events.on_now_or_later()).order_by("-starts_at")[:10],
            "memberships": page.memberships.select_related("user").order_by("created_at"),
            "member_form": AddMemberForm(),
        },
    )


@login_required
def edit_page(request, kind, pk):
    page, _ = _member_page(request, kind, pk)
    form = page_form_class(type(page))(request.POST or None, instance=page)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Changes saved.")
        return redirect(page.get_manage_url())
    return render(
        request, "events/manage/page_form.html", {"form": form, "kind_label": page.kind_label, "page": page}
    )


@require_POST
@login_required
def add_member(request, kind, pk):
    page, _ = _member_page(request, kind, pk, owner=True)
    form = AddMemberForm(request.POST)
    if form.is_valid():
        user = get_user_model().objects.filter(email__iexact=form.cleaned_data["email"]).first()
        if user is None:
            messages.error(request, "No liveaux account uses that email address. Ask them to sign up first.")
        elif page.memberships.filter(user=user).exists():
            messages.error(request, f"{user} is already a member.")
        else:
            page.memberships.create(user=user, role=form.cleaned_data["role"])
            messages.success(request, f"{user} can now manage {page.name}.")
    else:
        messages.error(request, "Enter a valid email address.")
    return redirect(page.get_manage_url())


@require_POST
@login_required
def remove_member(request, kind, pk, membership_pk):
    page, _ = _member_page(request, kind, pk, owner=True)
    membership = get_object_or_404(page.memberships, pk=membership_pk)
    owners = page.memberships.filter(role=Membership.OWNER)
    if membership.is_owner and owners.count() == 1:
        messages.error(request, "A page needs at least one owner. Make someone else owner first.")
    else:
        membership.delete()
        messages.success(request, f"{membership.user} no longer manages {page.name}.")
    return redirect(page.get_manage_url())


@login_required
def create_event(request, kind, pk):
    if kind not in EVENT_KINDS:
        raise Http404
    page, _ = _member_page(request, kind, pk)
    form = EventForm(request.POST or None, fixed_page=page)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.created_by = request.user
        event.save()
        form.save_m2m()
        messages.success(request, f"{event.title} is published.")
        return redirect(page.get_manage_url())
    return render(request, "events/manage/event_form.html", {"form": form, "page": page, "event": None})


def _editable_event(request, pk):
    event = get_object_or_404(Event.objects.select_related("venue", "promoter"), pk=pk)
    if not event.can_edit(request.user):
        raise PermissionDenied
    # Lock the page the user manages the event through, so it can't be moved away from them.
    if event.venue.is_member(request.user):
        return event, event.venue
    if event.promoter and event.promoter.is_member(request.user):
        return event, event.promoter
    return event, None  # superuser


@login_required
def edit_event(request, pk):
    event, page = _editable_event(request, pk)
    form = EventForm(request.POST or None, instance=event, fixed_page=page)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Changes saved.")
        return redirect(page.get_manage_url() if page else event)
    return render(request, "events/manage/event_form.html", {"form": form, "page": page, "event": event})


@login_required
def delete_event(request, pk):
    event, page = _editable_event(request, pk)
    if request.method == "POST":
        event.delete()
        messages.success(request, f"{event.title} is deleted.")
        return redirect(page.get_manage_url() if page else "events:event_list")
    return render(request, "events/manage/event_confirm_delete.html", {"event": event, "page": page})

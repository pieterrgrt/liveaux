from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from events.models import Event
from library.models import Item

from . import services
from .forms import CommentForm, ReportForm, ReviewForm
from .models import Comment, Like, Report, Review

SLOW_DOWN = "You're posting a lot in a short time. Wait a minute and try again."


def _set_side(request, side):
    """The page takes the colour of what it is about: Live for events, Aux for the library."""
    request.liveaux_side = side


def _back(request, fallback):
    """Back to where the form was, if that is on liveaux; otherwise to `fallback`."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        return redirect(target)
    return redirect(fallback)


def _item_or_event(request, kind, pk):
    if kind == "item":
        item = get_object_or_404(Item, pk=pk)
        if not item.visible_to(request.user):
            raise Http404
        return item
    if kind == "event":
        return get_object_or_404(Event, pk=pk)
    raise Http404


def _visible_review(request, pk):
    return get_object_or_404(Review.objects.visible_to(request.user).with_numbers(), pk=pk)


def _errors(form):
    return " ".join(e for errors in form.errors.values() for e in errors)


# Reviews


@login_required
def write_review(request, kind, pk):
    target = _item_or_event(request, kind, pk)
    _set_side(request, services.side_of(target))
    user = request.user
    mine = Review.objects.filter(user=user, **{kind: target}).first()
    if mine and mine.is_hidden:
        messages.error(request, "Your review was hidden by a moderator, so it can't be changed.")
        return redirect(target)
    if not services.can_review(target):
        messages.error(request, "You can review an event once it has started.")
        return redirect(target)

    form = ReviewForm(
        request.POST or None, instance=mine, user=user, score=mine.score if mine else services.own_score(user, target)
    )
    if request.method == "POST":
        if not mine and services.too_fast(user, "review"):
            messages.error(request, SLOW_DOWN)
            return redirect(target)
        if form.is_valid():
            form.save_name()
            review = form.save(commit=False)
            review.user = user
            setattr(review, kind, target)
            try:
                with transaction.atomic():
                    review.save()
            except IntegrityError:  # posted twice at once: the first one stands
                return redirect(target)
            services.save_score(user, target, form.cleaned_data["score"])
            messages.success(request, "Your review is up." if not mine else "Your review is saved.")
            return redirect(f"{target.get_absolute_url()}#reviews")
    return render(request, "social/review_form.html", {"form": form, "target": target, "kind": kind, "review": mine})


@require_POST
@login_required
def delete_review(request, pk):
    review = get_object_or_404(Review, pk=pk, user=request.user)
    target = review.target
    review.delete()
    where = "library" if review.kind == "item" else "log"
    messages.success(request, f"Your review is deleted. Your score stays in your {where}.")
    return redirect(target)


def review_detail(request, pk):
    review = _visible_review(request, pk)
    _set_side(request, review.side)
    user = request.user
    services.mark_liked(user, [review])
    comments = review.comments.visible_to(user).select_related("user")
    return render(
        request,
        "social/review_detail.html",
        {
            "review": review,
            "target": review.target,
            "comments": comments,
            "comment_form": CommentForm(user=user) if user.is_authenticated else None,
            "can_see_target": review.event_id is not None or user.is_authenticated,
            "meta_title": f"{review.target.title}, reviewed by {review.user.public_name}",
            "meta_description": "Contains spoilers." if review.contains_spoilers else review.body,
        },
    )


@require_POST
@login_required
def like(request, pk):
    review = get_object_or_404(Review.objects.filter(is_hidden=False), pk=pk)
    if review.user_id == request.user.pk:
        messages.error(request, "You can't like your own review.")
    else:
        deleted, _ = Like.objects.filter(user=request.user, review=review).delete()
        if not deleted:
            Like.objects.get_or_create(user=request.user, review=review)
    return _back(request, review)


# Comments


@require_POST
@login_required
def add_comment(request, kind, pk):
    if kind == "review":
        target = get_object_or_404(Review.objects.visible_to(request.user), pk=pk)
    else:
        target = _item_or_event(request, kind, pk)
    if services.too_fast(request.user, "comment"):
        messages.error(request, SLOW_DOWN)
        return _back(request, target)
    form = CommentForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, _errors(form))
        return _back(request, target)
    form.save_name()
    comment = form.save(commit=False)
    comment.user = request.user
    setattr(comment, kind, target)
    comment.save()
    return redirect(comment.get_absolute_url())


@require_POST
@login_required
def delete_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk, user=request.user)
    target = comment.target
    comment.delete()
    messages.success(request, "Your comment is deleted.")
    return _back(request, target)


# Moderation


def _content(kind, pk):
    models = {"review": Review, "comment": Comment}
    if kind not in models:
        raise Http404
    return get_object_or_404(models[kind], pk=pk)


@require_POST
@user_passes_test(lambda u: u.is_staff)
def hide(request, kind, pk):
    """Staff hide (or show again) a review or comment, straight from the page."""
    content = _content(kind, pk)
    content.is_hidden = not content.is_hidden
    content.save(update_fields=["is_hidden"])
    if content.is_hidden:
        content.reports.filter(status=Report.Status.OPEN).update(
            status=Report.Status.HIDDEN, resolved_at=timezone.now(), resolved_by=request.user
        )
    messages.success(request, "Hidden. Only staff can see it now." if content.is_hidden else "Visible again.")
    return _back(request, content.target if kind == "comment" else content)


@login_required
def report(request, kind, pk):
    content = _content(kind, pk)
    if content.is_hidden and not request.user.is_staff:
        raise Http404
    review = content if kind == "review" else content.review
    if review is not None and not Review.objects.visible_to(request.user).filter(pk=review.pk).exists():
        raise Http404
    if kind == "comment" and content.item and not content.item.visible_to(request.user):
        raise Http404
    page_of = content.target if kind == "comment" else content
    _set_side(request, services.side_of(review.target if review else content.target))
    if content.user_id == request.user.pk:
        messages.error(request, "That's yours. You can delete it instead.")
        return redirect(page_of.get_absolute_url())
    form = ReportForm(request.POST or None)
    if request.method == "POST":
        if services.too_fast(request.user, "report"):
            messages.error(request, SLOW_DOWN)
            return redirect(page_of.get_absolute_url())
        if form.is_valid():
            Report.objects.get_or_create(
                reporter=request.user, **{kind: content}, defaults={"reason": form.cleaned_data["reason"]}
            )
            messages.success(request, "Thanks. Someone at liveaux will have a look.")
            return redirect(page_of.get_absolute_url())
    return render(request, "social/report_form.html", {"form": form, "content": content, "kind": kind, "page_of": page_of})


# People


def person(request, pk):
    """Someone's reviews. Reviews are public by nature, even when their log and library are private."""
    owner = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    reviews = owner.reviews.visible_to(request.user).with_numbers().order_by("-created_at")
    return render(
        request,
        "social/person.html",
        {"owner": owner, "reviews": services.mark_liked(request.user, reviews[:100]), "review_count": reviews.count(), "is_own": owner == request.user},
    )

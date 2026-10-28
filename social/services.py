"""What the review and comment blocks need, shared by the views and the template tags."""

from datetime import timedelta

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from events.models import Event
from library.models import Entry, Item, Status
from logbook.models import LogEntry

from .forms import CommentForm, ReviewForm
from .models import Comment, Like, Report, Review

# How much someone can post before liveaux asks them to slow down: (how many, per how many seconds).
DEFAULT_LIMITS = {
    "comment": (5, 60),
    "review": (5, 600),
    "report": (10, 3600),
}
MODELS = {"comment": (Comment, "user"), "review": (Review, "user"), "report": (Report, "reporter")}


def too_fast(user, what):
    """True when the user has posted `what` too often lately. Counted in the database, no cache needed."""
    limit, seconds = getattr(settings, "SOCIAL_LIMITS", {}).get(what, DEFAULT_LIMITS[what])
    model, field = MODELS[what]
    since = timezone.now() - timedelta(seconds=seconds)
    return model.objects.filter(**{field: user, "created_at__gte": since}).count() >= limit


def kind_of(target):
    return "item" if isinstance(target, Item) else "event"


def side_of(target):
    return "aux" if isinstance(target, Item) else "live"


def own_score(user, target):
    if not user.is_authenticated:
        return None
    if isinstance(target, Item):
        return Entry.objects.filter(user=user, item=target).values_list("score", flat=True).first()
    return LogEntry.objects.filter(user=user, event=target).values_list("rating", flat=True).first()


def save_score(user, target, score):
    """Puts the score where it belongs: the library entry or the log entry, made if needed."""
    if isinstance(target, Item):
        entry, created = Entry.objects.get_or_create(
            user=user, item=target, defaults={"status": Status.COMPLETED, "score": score}
        )
        if not created and entry.score != score:
            entry.score = score
            entry.save(update_fields=["score", "updated_at"])
    else:
        entry, created = LogEntry.objects.get_or_create(user=user, event=target, defaults={"rating": score})
        if not created and entry.rating != score:
            entry.rating = score
            entry.save(update_fields=["rating", "updated_at"])


def can_review(target):
    """Events can be reviewed once they have started, like "I was there". Items any time."""
    return not isinstance(target, Event) or target.has_started


def mark_liked(user, reviews):
    """Sets `is_liked` on each review: whether this user liked it. Returns them as a list."""
    reviews = list(reviews)
    liked = set()
    if user.is_authenticated:
        liked = set(Like.objects.filter(user=user, review__in=[r.pk for r in reviews]).values_list("review_id", flat=True))
    for review in reviews:
        review.is_liked = review.pk in liked
    return reviews


def reviews_block(request, target, sort=None):
    """Everything the reviews partial shows for one item or event."""
    user = request.user
    kind = kind_of(target)
    reviews = Review.objects.filter(**{kind: target}).with_numbers()
    visible = reviews.visible_to(user)
    mine = reviews.filter(user=user).first() if user.is_authenticated else None
    others = visible.exclude(user=user) if user.is_authenticated else visible
    sort = sort or request.GET.get("reviews", "")
    others = others.order_by("-like_count", "-created_at") if sort == "liked" else others.order_by("-created_at")
    others = mark_liked(user, others[:30])

    public = Review.objects.filter(**{kind: target}, is_hidden=False)
    numbers = public.aggregate(count=Count("pk"))
    scores = [r.score for r in public.with_numbers() if r.score]
    comments = Comment.objects.filter(**{kind: target}).visible_to(user).select_related("user")
    context = {
        "target": target,
        "kind": kind,
        "mine": mine,
        "reviews": others,
        "sort": "liked" if sort == "liked" else "new",
        "review_count": numbers["count"],
        "average": round(sum(scores) / len(scores), 1) if scores else None,
        "score_count": len(scores),
        "can_review": can_review(target),
        "comments": list(comments.order_by("-created_at")[:50])[::-1],
        "comment_count": comments.count(),
    }
    if user.is_authenticated:
        if not mine and context["can_review"]:
            context["review_form"] = ReviewForm(user=user, score=own_score(user, target))
        elif mine and not mine.is_hidden:
            context["review_form"] = ReviewForm(instance=mine, user=user, score=mine.score)
        context["comment_form"] = CommentForm(user=user)
    return context


def latest(kind, limit=6):
    """The newest reviews anyone can see, of items (aux) or events (live)."""
    reviews = Review.objects.public().filter(**{f"{kind}__isnull": False}).with_numbers()
    return list(reviews.order_by("-created_at")[:limit])

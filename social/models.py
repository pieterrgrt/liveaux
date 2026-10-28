from django.conf import settings
from django.db import models
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse

from events.models import Event
from library.models import Entry, Item, Source
from logbook.models import LogEntry

REVIEW_MAX = 5000
COMMENT_MAX = 1000


def _exactly_one(*fields):
    """A condition that holds when exactly one of the foreign keys is set."""
    condition = Q()
    for field in fields:
        condition |= Q(**{f"{f}__isnull": f != field for f in fields})
    return condition


def _item_is_visible(user):
    """Items added by hand are private: only their maker and people who track them see talk about them."""
    public = Q(item__isnull=True) | ~Q(item__source=Source.MANUAL)
    if user is None or not user.is_authenticated:
        return public
    tracks = Entry.objects.filter(item=OuterRef("item"), user=user)
    return public | Q(item__created_by=user) | Q(Exists(tracks))


def _is_staff(user):
    return bool(user and user.is_authenticated and user.is_staff)


class ReviewQuerySet(models.QuerySet):
    def visible_to(self, user):
        qs = self.filter(_item_is_visible(user))
        return qs if _is_staff(user) else qs.filter(is_hidden=False)

    def public(self):
        """For lists anyone can see: nothing hidden, nothing about items added by hand."""
        return self.filter(_item_is_visible(None), is_hidden=False)

    def with_numbers(self):
        """Adds the reviewer's score (from their library or log), `like_count` and `comment_count`."""
        item_score = Entry.objects.filter(user=OuterRef("user"), item=OuterRef("item")).values("score")[:1]
        event_score = LogEntry.objects.filter(user=OuterRef("user"), event=OuterRef("event")).values("rating")[:1]
        likes = Like.objects.filter(review=OuterRef("pk")).order_by().values("review").annotate(n=Count("pk")).values("n")
        comments = (
            Comment.objects.filter(review=OuterRef("pk"), is_hidden=False)
            .order_by()
            .values("review")
            .annotate(n=Count("pk"))
            .values("n")
        )
        return self.select_related("user", "item", "event__venue", "event__category").annotate(
            item_score=Subquery(item_score),
            event_score=Subquery(event_score),
            like_count=Coalesce(Subquery(likes), 0),
            comment_count=Coalesce(Subquery(comments), 0),
        )


class Review(models.Model):
    """Someone's public review of a library item or an event. The score lives in their library or log."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True, related_name="reviews")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name="reviews")
    body = models.TextField("review", max_length=REVIEW_MAX)
    contains_spoilers = models.BooleanField("contains spoilers", default=False)
    is_hidden = models.BooleanField("hidden", default=False, help_text="Hidden by a moderator: only staff see it.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=_exactly_one("item", "event"), name="review_one_target"),
            models.UniqueConstraint(fields=["user", "item"], condition=Q(item__isnull=False), name="unique_item_review"),
            models.UniqueConstraint(
                fields=["user", "event"], condition=Q(event__isnull=False), name="unique_event_review"
            ),
        ]

    def __str__(self):
        return f"{self.user.public_name} on {self.target}"

    def get_absolute_url(self):
        return reverse("social:review", args=[self.pk])

    @property
    def target(self):
        return self.item or self.event

    @property
    def kind(self):
        return "item" if self.item_id else "event"

    @property
    def side(self):
        return "aux" if self.item_id else "live"

    @property
    def score(self):
        """The reviewer's own score: annotated by `with_numbers()`, or else looked up."""
        if hasattr(self, "item_score"):
            return self.item_score if self.item_id else self.event_score
        if self.item_id:
            return Entry.objects.filter(user=self.user_id, item=self.item_id).values_list("score", flat=True).first()
        return LogEntry.objects.filter(user=self.user_id, event=self.event_id).values_list("rating", flat=True).first()


class CommentQuerySet(models.QuerySet):
    def visible_to(self, user):
        return self if _is_staff(user) else self.filter(is_hidden=False)


class Comment(models.Model):
    """A short reply: to a review, or straight on an event or item ("anyone going?"). Flat, no threads."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    review = models.ForeignKey(Review, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, null=True, blank=True, related_name="comments")
    body = models.TextField("comment", max_length=COMMENT_MAX)
    is_hidden = models.BooleanField("hidden", default=False, help_text="Hidden by a moderator: only staff see it.")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CommentQuerySet.as_manager()

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=_exactly_one("review", "item", "event"), name="comment_one_target"),
        ]

    def __str__(self):
        return f"{self.user.public_name}: {self.body[:40]}"

    @property
    def target(self):
        return self.review or self.item or self.event

    def get_absolute_url(self):
        return f"{self.target.get_absolute_url()}#comment-{self.pk}"


class Like(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_likes")
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "review"], name="unique_like")]

    def __str__(self):
        return f"{self.user.public_name} likes {self.review}"


class Report(models.Model):
    """Someone flags a review or comment. Staff hide it or dismiss the report, in the admin."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        HIDDEN = "hidden", "Hidden"
        DISMISSED = "dismissed", "Dismissed"

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    review = models.ForeignKey(Review, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    comment = models.ForeignKey(Comment, on_delete=models.CASCADE, null=True, blank=True, related_name="reports")
    reason = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=_exactly_one("review", "comment"), name="report_one_target"),
            models.UniqueConstraint(
                fields=["reporter", "review"], condition=Q(review__isnull=False), name="unique_review_report"
            ),
            models.UniqueConstraint(
                fields=["reporter", "comment"], condition=Q(comment__isnull=False), name="unique_comment_report"
            ),
        ]

    def __str__(self):
        return f"Report on {self.target}"

    @property
    def target(self):
        return self.review or self.comment

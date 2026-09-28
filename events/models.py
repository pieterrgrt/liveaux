from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Membership(models.Model):
    """A user who manages a venue, promoter or artist page."""

    OWNER = "owner"
    EDITOR = "editor"
    ROLE_CHOICES = [(OWNER, "Owner"), (EDITOR, "Editor")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=EDITOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    @property
    def is_owner(self):
        return self.role == self.OWNER


class Page(models.Model):
    """Shared behaviour of venues, promoters and artists: members and followers."""

    kind = None  # "venue", "promoter" or "artist"; set on each subclass

    class Meta:
        abstract = True

    def get_absolute_url(self):
        return reverse(f"events:{self.kind}_detail", args=[self.pk])

    def get_manage_url(self):
        return reverse("events:manage_page", args=[self.kind, self.pk])

    def membership_for(self, user):
        if not user.is_authenticated:
            return None
        return self.memberships.filter(user=user).first()

    def is_member(self, user):
        return self.membership_for(user) is not None

    def upcoming_events(self):
        return self.events.filter(starts_at__gte=timezone.now()).select_related("venue")


class Venue(Page):
    kind = "venue"

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300, blank=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, default="Berlin")
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="VenueMember", related_name="managed_venues", blank=True
    )
    followers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="followed_venues", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Promoter(Page):
    kind = "promoter"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="PromoterMember", related_name="managed_promoters", blank=True
    )
    followers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="followed_promoters", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Artist(Page):
    kind = "artist"

    name = models.CharField(max_length=200)
    hometown = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ArtistMember", related_name="managed_artists", blank=True
    )
    followers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="followed_artists", blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VenueMember(Membership):
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["venue", "user"], name="unique_venue_member")]


class PromoterMember(Membership):
    promoter = models.ForeignKey(Promoter, on_delete=models.CASCADE, related_name="memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["promoter", "user"], name="unique_promoter_member")]


class ArtistMember(Membership):
    artist = models.ForeignKey(Artist, on_delete=models.CASCADE, related_name="memberships")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["artist", "user"], name="unique_artist_member")]


PAGE_MODELS = {model.kind: model for model in (Venue, Promoter, Artist)}


class Event(models.Model):
    title = models.CharField(max_length=200)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="events")
    promoter = models.ForeignKey(
        Promoter, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )
    artists = models.ManyToManyField(Artist, related_name="events", blank=True)
    starts_at = models.DateTimeField()
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    ticket_url = models.URLField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    saved_by = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="saved_events", blank=True)

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return f"{self.title} ({self.starts_at:%d-%m-%Y})"

    def get_absolute_url(self):
        return reverse("events:event_detail", args=[self.pk])

    @property
    def month(self):
        """(year, month) in local time, used to group events by month in templates."""
        local = timezone.localtime(self.starts_at)
        return (local.year, local.month)

    def can_edit(self, user):
        """Members of the event's venue or promoter may edit it."""
        if not user.is_authenticated:
            return False
        if user.is_superuser or self.venue.is_member(user):
            return True
        return self.promoter is not None and self.promoter.is_member(user)

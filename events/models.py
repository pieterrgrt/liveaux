from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
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
    kind_label = None  # how the kind is called on the site

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
        return self.events.on_now_or_later().select_related("venue", "category")


class CategoryManager(models.Manager):
    def get_by_natural_key(self, slug):
        return self.get(slug=slug)


class Category(models.Model):
    """What kind of event: music, exhibition, film, theatre, ..."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)
    position = models.PositiveSmallIntegerField(default=0, help_text="Lower comes first in filters.")

    objects = CategoryManager()

    class Meta:
        ordering = ["position", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def natural_key(self):
        return (self.slug,)


class City(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "cities"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:city_week", args=[self.slug])


class Venue(Page):
    kind = "venue"
    kind_label = "venue"

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300, blank=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="venues")
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
    kind_label = "organiser"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    website = models.URLField(blank=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="PromoterMember", related_name="managed_promoters", blank=True
    )
    followers = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="followed_promoters", blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "organiser"

    def __str__(self):
        return self.name


class Artist(Page):
    kind = "artist"
    kind_label = "artist"

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


class EventQuerySet(models.QuerySet):
    def on_now_or_later(self):
        """Events that haven't finished: upcoming ones, and ones running now (like an exhibition)."""
        now = timezone.now()
        return self.filter(Q(starts_at__gte=now) | Q(ends_at__gte=now))

    def started(self):
        """Events that have begun: finished ones and ones still running."""
        return self.filter(starts_at__lt=timezone.now())

    def overlapping(self, start, end):
        """Events that are on at some point between start and end."""
        return self.filter(starts_at__lt=end).filter(Q(starts_at__gte=start) | Q(ends_at__gte=start))


class Event(models.Model):
    title = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="events")
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="events")
    promoter = models.ForeignKey(
        Promoter, on_delete=models.SET_NULL, null=True, blank=True, related_name="events", verbose_name="organiser"
    )
    artists = models.ManyToManyField(Artist, related_name="events", blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(
        null=True, blank=True, help_text="For exhibitions, film runs and festivals: the last day it's on."
    )
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    ticket_url = models.URLField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    saved_by = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="saved_events", blank=True)

    objects = EventQuerySet.as_manager()

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

    @property
    def has_started(self):
        return self.starts_at <= timezone.now()

    @property
    def is_multi_day(self):
        """Runs over more than one day, like an exhibition or a festival."""
        return self.ends_at is not None and timezone.localdate(self.ends_at) > timezone.localdate(self.starts_at)

    @property
    def is_running(self):
        """Started, and still on."""
        return self.is_multi_day and self.has_started and self.ends_at >= timezone.now()

    def clean(self):
        super().clean()
        if self.ends_at and self.starts_at and self.ends_at < self.starts_at:
            raise ValidationError({"ends_at": "The end can't be before the start."})

    def can_edit(self, user):
        """Members of the event's venue or promoter may edit it."""
        if not user.is_authenticated:
            return False
        if user.is_superuser or self.venue.is_member(user):
            return True
        return self.promoter is not None and self.promoter.is_member(user)


class EventSubmission(models.Model):
    """An event sent in by a venue through the public form. Becomes an Event once approved in the admin."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    STATUS_CHOICES = [(PENDING, "Waiting for review"), (APPROVED, "Approved"), (REJECTED, "Rejected")]

    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="event_submissions"
    )
    venue = models.ForeignKey(
        Venue, on_delete=models.SET_NULL, null=True, blank=True, related_name="submissions",
        help_text="Pick the venue, or fill in the new venue fields below.",
    )
    new_venue_name = models.CharField("new venue", max_length=200, blank=True)
    new_venue_address = models.CharField("address", max_length=300, blank=True)
    new_venue_district = models.CharField("district", max_length=100, blank=True)
    new_venue_city = models.ForeignKey(
        City, on_delete=models.SET_NULL, null=True, blank=True, related_name="+", verbose_name="city"
    )
    title = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="+")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True, help_text="Only for things that run several days.")
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    ticket_url = models.URLField(blank=True)
    relation = models.CharField(
        "your role", max_length=200, help_text="For example: curator at the museum, or booker at the club.",
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    review_note = models.TextField(blank=True, help_text="Sent to the submitter when you reject.")
    event = models.OneToOneField(Event, on_delete=models.SET_NULL, null=True, blank=True, related_name="submission")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def venue_name(self):
        return self.venue.name if self.venue else self.new_venue_name

    def approve(self):
        """Publish the event, creating the venue first when it is new."""
        if self.status != self.PENDING:
            raise ValueError("Only pending submissions can be approved.")
        venue = self.venue
        if venue is None:
            venue = Venue.objects.create(
                name=self.new_venue_name,
                address=self.new_venue_address,
                district=self.new_venue_district,
                city=self.new_venue_city,
            )
            self.venue = venue
        self.event = Event.objects.create(
            title=self.title,
            category=self.category,
            venue=venue,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            description=self.description,
            price=self.price,
            ticket_url=self.ticket_url,
            created_by=self.submitted_by,
        )
        self.status = self.APPROVED
        self.reviewed_at = timezone.now()
        self.save()
        return self.event

    def reject(self, note=""):
        if self.status != self.PENDING:
            raise ValueError("Only pending submissions can be rejected.")
        self.status = self.REJECTED
        if note:
            self.review_note = note
        self.reviewed_at = timezone.now()
        self.save()

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


class MediaType(models.TextChoices):
    MOVIE = "movie", "Film"
    TV = "tv", "Series"
    ANIME = "anime", "Anime"
    BOOK = "book", "Book"
    COMIC = "comic", "Comic"
    MANGA = "manga", "Manga"
    GAME = "game", "Game"
    BOARDGAME = "boardgame", "Board game"
    MUSIC = "music", "Album"
    PODCAST = "podcast", "Podcast"


# How each kind of media is counted and checked in.
#   single:   one check-in finishes it (a film, a book, an album). Checking in again is a rewatch/reread.
#   episodic: each check-in is one episode, chapter or issue; it's finished when progress reaches the total.
#   sessions: each check-in is a session (a game played for a few hours, a board game night).
MEDIA = {
    MediaType.MOVIE: {"behaviour": "single", "unit": "film", "verb": "Watched", "plural": "Films"},
    MediaType.TV: {"behaviour": "episodic", "unit": "episode", "verb": "Watched", "plural": "Series"},
    MediaType.ANIME: {"behaviour": "episodic", "unit": "episode", "verb": "Watched", "plural": "Anime"},
    MediaType.BOOK: {"behaviour": "single", "unit": "page", "verb": "Read", "plural": "Books"},
    MediaType.COMIC: {"behaviour": "episodic", "unit": "issue", "verb": "Read", "plural": "Comics"},
    MediaType.MANGA: {"behaviour": "episodic", "unit": "chapter", "verb": "Read", "plural": "Manga"},
    MediaType.GAME: {"behaviour": "sessions", "unit": "session", "verb": "Played", "plural": "Games"},
    MediaType.BOARDGAME: {"behaviour": "sessions", "unit": "play", "verb": "Played", "plural": "Board games"},
    MediaType.MUSIC: {"behaviour": "single", "unit": "track", "verb": "Listened", "plural": "Albums"},
    MediaType.PODCAST: {"behaviour": "episodic", "unit": "episode", "verb": "Listened", "plural": "Podcasts"},
}


class Source(models.TextChoices):
    TMDB = "tmdb", "TMDB"
    ANILIST = "anilist", "AniList"
    OPENLIBRARY = "openlibrary", "Open Library"
    MUSICBRAINZ = "musicbrainz", "MusicBrainz"
    ITUNES = "itunes", "Apple Podcasts"
    IGDB = "igdb", "IGDB"
    MANUAL = "manual", "Added by hand"


class Item(models.Model):
    """A work: a film, series, book, game, album... Shared by everyone who tracks it."""

    media_type = models.CharField(max_length=20, choices=MediaType.choices)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    source_id = models.CharField(max_length=100, blank=True)
    title = models.CharField(max_length=300)
    original_title = models.CharField(max_length=300, blank=True)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    release_date = models.DateField(null=True, blank=True, help_text="First release. For a series: the next episode.")
    creator = models.CharField(
        max_length=300, blank=True, help_text="Director, author, artist, developer or studio."
    )
    description = models.TextField(blank=True)
    genres = models.JSONField(default=list, blank=True)
    runtime = models.PositiveIntegerField(
        null=True, blank=True, help_text="Minutes: the film, one episode, or the whole album."
    )
    total = models.PositiveIntegerField(
        null=True, blank=True, help_text="Episodes, pages, chapters, issues or tracks in all."
    )
    status_text = models.CharField(max_length=60, blank=True, help_text="As the source says, e.g. 'Ended'.")
    url = models.URLField(blank=True, help_text="Where the details come from.")
    cover_url = models.URLField(max_length=500, blank=True)
    # The cover is fetched by liveaux and served from here, so visitors' browsers never contact the source.
    cover = models.BinaryField(null=True, blank=True, editable=False)
    cover_type = models.CharField(max_length=40, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="For items added by hand: who added it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "media_type", "source_id"],
                condition=~Q(source="manual"),
                name="unique_item_per_source",
            )
        ]
        indexes = [models.Index(fields=["media_type", "title"])]

    def __str__(self):
        return f"{self.title} ({self.year})" if self.year else self.title

    def get_absolute_url(self):
        return reverse("library:item", args=[self.pk])

    @property
    def info(self):
        return MEDIA[self.media_type]

    @property
    def behaviour(self):
        return self.info["behaviour"]

    @property
    def is_manual(self):
        return self.source == Source.MANUAL

    @property
    def has_episodes(self):
        return self.media_type == MediaType.TV

    @property
    def length_text(self):
        unit = self.info["unit"]
        parts = []
        if self.total and self.media_type != MediaType.MOVIE:
            parts.append(f"{self.total} {unit}{'s' if self.total != 1 else ''}")
        if self.runtime:
            per = " an episode" if self.media_type in (MediaType.TV, MediaType.ANIME) else ""
            parts.append(f"{self.runtime} min{per}")
        return " · ".join(parts)

    @property
    def check_in_label(self):
        verb = self.info["verb"]
        unit = self.info["unit"]
        if self.behaviour == "single":
            return f"{verb} to it" if verb == "Listened" else f"{verb} it"
        if self.behaviour == "sessions":
            return f"Log a {unit}"
        article = "an" if unit[0] in "aeiou" else "a"
        return f"{verb}{' to' if verb == 'Listened' else ''} {article} {unit}"

    @property
    def cover_src(self):
        if self.cover or self.cover_url:
            return reverse("library:cover", args=[self.pk])
        return ""

    def visible_to(self, user):
        """Items added by hand are private to whoever added or tracks them."""
        if not self.is_manual:
            return True
        return user.is_authenticated and (
            self.created_by_id == user.pk or self.entries.filter(user=user).exists()
        )


class Episode(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="episodes")
    season = models.PositiveSmallIntegerField()
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=300, blank=True)
    air_date = models.DateField(null=True, blank=True)
    runtime = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["season", "number"]
        constraints = [models.UniqueConstraint(fields=["item", "season", "number"], name="unique_episode")]

    def __str__(self):
        return f"{self.item.title} {self.code}"

    @property
    def code(self):
        return f"S{self.season:02d}E{self.number:02d}"

    @property
    def has_aired(self):
        return self.air_date is not None and self.air_date <= timezone.localdate()


class Status(models.TextChoices):
    PLANNING = "planning", "Planning"
    IN_PROGRESS = "in_progress", "In progress"
    PAUSED = "paused", "Paused"
    COMPLETED = "completed", "Completed"
    DROPPED = "dropped", "Dropped"


class Entry(models.Model):
    """One person's record of an item: where they are with it and what they thought."""

    SCORE_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="library_entries")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="entries")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PLANNING)
    score = models.PositiveSmallIntegerField(
        choices=SCORE_CHOICES,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="1 to 10.",
    )
    progress = models.PositiveIntegerField(default=0)
    repeats = models.PositiveSmallIntegerField(default=0, help_text="Times rewatched, reread or replayed.")
    started_on = models.DateField(null=True, blank=True)
    finished_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name_plural = "entries"
        constraints = [models.UniqueConstraint(fields=["user", "item"], name="unique_library_entry")]

    def __str__(self):
        return f"{self.user}: {self.item}"

    @property
    def percent(self):
        if not self.item.total:
            return None
        return min(100, round(100 * self.progress / self.item.total))


class Play(models.Model):
    """A check-in: one viewing, reading, listening or session, at a moment in time."""

    class Via(models.TextChoices):
        MANUAL = "manual", "Checked in"
        PLEX = "plex", "Plex"
        JELLYFIN = "jellyfin", "Jellyfin"
        API = "api", "API"
        IMPORT = "import", "Import"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="plays")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="plays")
    episode = models.ForeignKey(Episode, on_delete=models.SET_NULL, null=True, blank=True, related_name="plays")
    played_at = models.DateTimeField(default=timezone.now)
    minutes = models.PositiveIntegerField(null=True, blank=True)
    via = models.CharField(max_length=20, choices=Via.choices, default=Via.MANUAL)
    note = models.CharField(max_length=280, blank=True)

    class Meta:
        ordering = ["-played_at"]
        indexes = [models.Index(fields=["user", "played_at"])]

    def __str__(self):
        return f"{self.user}: {self.episode or self.item} at {self.played_at:%Y-%m-%d %H:%M}"


class MediaList(models.Model):
    """A list someone keeps. A smart list fills itself from rules instead of hand-picked items."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="media_lists")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_public = models.BooleanField(
        "public", default=False, help_text="Anyone with the link can see it, and follow it by RSS."
    )
    is_smart = models.BooleanField(
        "smart list", default=False, help_text="Fill the list from your library with the rules below."
    )
    rules = models.JSONField(default=dict, blank=True)
    items = models.ManyToManyField(Item, through="ListItem", related_name="lists", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "list"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("library:list_detail", args=[self.pk])

    def visible_to(self, user):
        return self.is_public or self.user_id == user.pk

    def entries_for_rules(self):
        """The owner's entries that match the smart rules."""
        entries = self.user.library_entries.select_related("item")
        rules = self.rules or {}
        if rules.get("media_type"):
            entries = entries.filter(item__media_type=rules["media_type"])
        if rules.get("status"):
            entries = entries.filter(status=rules["status"])
        if rules.get("min_score"):
            entries = entries.filter(score__gte=rules["min_score"])
        if rules.get("year_from"):
            entries = entries.filter(item__year__gte=rules["year_from"])
        if rules.get("year_to"):
            entries = entries.filter(item__year__lte=rules["year_to"])
        genre = (rules.get("genre") or "").strip().lower()
        if genre:
            entries = [e for e in entries if genre in (g.lower() for g in e.item.genres)]
        order = {"score": ["-score", "item__title"], "year": ["-item__year", "item__title"]}.get(
            rules.get("order"), ["-updated_at"]
        )
        if isinstance(entries, list):
            return entries
        return entries.order_by(*order)

    def get_items(self):
        if self.is_smart:
            return [e.item for e in self.entries_for_rules()]
        return [li.item for li in self.list_items.select_related("item")]


class ListItem(models.Model):
    media_list = models.ForeignKey(MediaList, on_delete=models.CASCADE, related_name="list_items")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="+")
    position = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "added_at"]
        constraints = [models.UniqueConstraint(fields=["media_list", "item"], name="unique_list_item")]


class Copy(models.Model):
    """Something in someone's collection: a physical or digital copy of an item."""

    class Format(models.TextChoices):
        UHD = "uhd", "4K Blu-ray"
        BLURAY = "bluray", "Blu-ray"
        DVD = "dvd", "DVD"
        VHS = "vhs", "VHS"
        HARDCOVER = "hardcover", "Hardcover"
        PAPERBACK = "paperback", "Paperback"
        EBOOK = "ebook", "E-book"
        AUDIOBOOK = "audiobook", "Audiobook"
        VINYL = "vinyl", "Vinyl"
        CD = "cd", "CD"
        CASSETTE = "cassette", "Cassette"
        CARTRIDGE = "cartridge", "Cartridge / disc"
        BOX = "box", "Box"
        DIGITAL = "digital", "Digital file"
        STREAMING = "streaming", "Digital purchase"
        OTHER = "other", "Other"

    class Resolution(models.TextChoices):
        SD = "sd", "SD"
        HD = "720p", "720p"
        FULLHD = "1080p", "1080p"
        UHD = "2160p", "4K"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="copies")
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="copies")
    format = models.CharField(max_length=20, choices=Format.choices)
    resolution = models.CharField(max_length=10, choices=Resolution.choices, blank=True)
    acquired_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["item__title"]
        verbose_name_plural = "copies"

    def __str__(self):
        return f"{self.item} on {self.get_format_display()}"

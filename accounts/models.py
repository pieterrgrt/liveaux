import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    """Users log in with their email address; there is no username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields["is_staff"] or not extra_fields["is_superuser"]:
            raise ValueError("A superuser needs is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField("email address", unique=True)
    display_name = models.CharField(max_length=100, blank=True)
    log_is_public = models.BooleanField(
        "public log",
        default=False,
        help_text="Let anyone with the link see the events you went to, with your name, ratings and notes.",
    )
    library_is_public = models.BooleanField(
        "public library",
        default=False,
        help_text="Let anyone with the link see what you watch, read, play and listen to, with your scores.",
    )
    # A secret for the calendar feed, media server webhooks and the API. Made on first use.
    api_token = models.CharField(max_length=64, blank=True, db_index=True, editable=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.display_name or self.email

    @property
    def public_name(self):
        """Name shown on a public log. Never the email address."""
        return self.display_name or "A liveaux fan"

    @property
    def initial(self):
        """One letter for the account button: from the name, or else the email address."""
        return (self.display_name or self.email or "?")[:1].upper()

    def get_api_token(self):
        if not self.api_token:
            self.reset_api_token()
        return self.api_token

    def reset_api_token(self):
        self.api_token = secrets.token_urlsafe(32)
        self.save(update_fields=["api_token"])

    def get_full_name(self):
        return str(self)

    def get_short_name(self):
        return str(self)

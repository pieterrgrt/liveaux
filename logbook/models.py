from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from events.models import Event


class LogEntry(models.Model):
    """A show someone went to. Private unless the user makes their log public."""

    RATING_CHOICES = [(n, str(n)) for n in range(10, 0, -1)]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="log_entries")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="log_entries")
    rating = models.PositiveSmallIntegerField(
        choices=RATING_CHOICES,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text="1 to 10.",
    )
    note = models.CharField(max_length=280, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event__starts_at"]
        verbose_name_plural = "log entries"
        constraints = [models.UniqueConstraint(fields=["user", "event"], name="unique_log_entry")]

    def __str__(self):
        return f"{self.user} at {self.event}"

    def get_edit_url(self):
        return reverse("logbook:edit", args=[self.pk])

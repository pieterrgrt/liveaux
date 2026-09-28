from django.db import models
from django.urls import reverse
from django.utils import timezone


class Venue(models.Model):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300, blank=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, default="Berlin")
    website = models.URLField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("events:venue_detail", args=[self.pk])


class Event(models.Model):
    title = models.CharField(max_length=200)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="events")
    starts_at = models.DateTimeField()
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    ticket_url = models.URLField(blank=True)

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

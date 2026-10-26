from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from library import providers, services
from library.models import Item, MediaType, Source, Status


class Command(BaseCommand):
    help = "Fetch new episodes and release dates for what people follow. Run once a day."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Refresh every item, not just running ones.")

    def handle(self, *args, all=False, **options):
        items = Item.objects.exclude(source=Source.MANUAL)
        if not all:
            today = timezone.localdate()
            followed = Q(entries__status__in=[Status.PLANNING, Status.IN_PROGRESS, Status.PAUSED])
            running = Q(media_type__in=[MediaType.TV, MediaType.ANIME, MediaType.MANGA, MediaType.PODCAST]) & ~Q(
                status_text__in=["Ended", "Canceled", "Finished", "Cancelled"]
            )
            upcoming = Q(release_date__gte=today - timedelta(days=7)) | Q(release_date__isnull=True)
            stale = Q(refreshed_at__isnull=True) | Q(refreshed_at__lt=timezone.now() - timedelta(hours=20))
            items = items.filter(followed & (running | upcoming) & stale)
        refreshed = failed = 0
        for item in items.distinct():
            try:
                services.refresh_item(item)
                refreshed += 1
            except providers.ProviderError as error:
                failed += 1
                self.stderr.write(f"{item}: {error}")
        self.stdout.write(f"Refreshed {refreshed} item(s), {failed} failed.")

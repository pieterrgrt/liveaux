from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from library import providers, ratings, services
from library.models import Item, MediaType, Source, Status


class Command(BaseCommand):
    help = "Fetch new episodes, release dates and scores from elsewhere for what people follow. Run once a day."

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Refresh every item, not just running ones.")
        parser.add_argument("--no-ratings", action="store_true", help="Leave the scores from elsewhere alone.")
        parser.add_argument(
            "--ratings-limit", type=int, default=300, help="At most this many items' scores per run (default 300)."
        )

    def handle(self, *args, all=False, no_ratings=False, ratings_limit=300, **options):
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

        if no_ratings:
            return
        # Scores from elsewhere for everything someone tracks, stalest first, so item pages open with fresh ones.
        tracked = (
            Item.objects.exclude(source=Source.MANUAL)
            .filter(entries__status__in=[s for s in Status.values if s != Status.DROPPED])
            .distinct()
            .order_by("refreshed_at")
        )
        scored = 0
        for item in tracked:
            if scored >= ratings_limit:
                break
            if ratings.is_stale(item) and ratings.refresh(item):
                scored += 1
        self.stdout.write(f"Fetched scores from elsewhere for {scored} item(s).")

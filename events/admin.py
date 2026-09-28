from django.contrib import admin, messages
from django.core.mail import send_mail
from django.urls import reverse

from .models import (
    Artist,
    ArtistMember,
    Category,
    City,
    Event,
    EventSubmission,
    Promoter,
    PromoterMember,
    Venue,
    VenueMember,
)


class VenueMemberInline(admin.TabularInline):
    model = VenueMember
    extra = 1
    autocomplete_fields = ["user"]


class PromoterMemberInline(admin.TabularInline):
    model = PromoterMember
    extra = 1
    autocomplete_fields = ["user"]


class ArtistMemberInline(admin.TabularInline):
    model = ArtistMember
    extra = 1
    autocomplete_fields = ["user"]


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "position"]
    list_editable = ["position"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    search_fields = ["name"]


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "city"]
    list_filter = ["city"]
    search_fields = ["name", "district"]
    inlines = [VenueMemberInline]
    exclude = ["followers"]


@admin.register(Promoter)
class PromoterAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]
    inlines = [PromoterMemberInline]
    exclude = ["followers"]


@admin.register(Artist)
class ArtistAdmin(admin.ModelAdmin):
    list_display = ["name", "hometown"]
    search_fields = ["name"]
    inlines = [ArtistMemberInline]
    exclude = ["followers"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "venue", "starts_at", "ends_at", "price"]
    list_filter = ["category", "venue__city", "venue"]
    search_fields = ["title", "venue__name"]
    date_hierarchy = "starts_at"
    autocomplete_fields = ["venue", "promoter", "artists"]
    exclude = ["saved_by"]
    readonly_fields = ["created_by"]


def _notify(submission, subject, body):
    send_mail(subject, body, None, [submission.submitted_by.email], fail_silently=True)


@admin.register(EventSubmission)
class EventSubmissionAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "venue_name", "starts_at", "submitted_by", "status", "created_at"]
    list_filter = ["status", "category"]
    search_fields = ["title", "venue__name", "new_venue_name", "submitted_by__email"]
    autocomplete_fields = ["venue"]
    readonly_fields = ["submitted_by", "status", "event", "created_at", "reviewed_at"]
    actions = ["approve", "reject"]
    fieldsets = [
        ("Review", {"fields": ["status", "review_note", "event", "submitted_by", "created_at", "reviewed_at"]}),
        ("Venue", {"fields": ["venue", "new_venue_name", "new_venue_address", "new_venue_district", "new_venue_city"]}),
        (
            "Event",
            {"fields": ["title", "category", "starts_at", "ends_at", "price", "ticket_url", "description", "relation"]},
        ),
    ]

    @admin.action(description="Approve and publish selected submissions")
    def approve(self, request, queryset):
        approved = 0
        for submission in queryset.filter(status=EventSubmission.PENDING).select_related("submitted_by"):
            if submission.venue is None and submission.new_venue_city is None:
                self.message_user(request, f"{submission}: pick a venue or a city first.", messages.ERROR)
                continue
            event = submission.approve()
            url = request.build_absolute_uri(reverse("events:event_detail", args=[event.pk]))
            _notify(submission, f"{event.title} is on liveaux", f"Your event is published: {url}")
            approved += 1
        self.message_user(request, f"{approved} submission(s) approved and published.")

    @admin.action(description="Reject selected submissions")
    def reject(self, request, queryset):
        rejected = 0
        for submission in queryset.filter(status=EventSubmission.PENDING).select_related("submitted_by"):
            submission.reject()
            body = f"We didn't publish {submission.title}."
            if submission.review_note:
                body += f"\n\n{submission.review_note}"
            _notify(submission, f"About your event {submission.title}", body)
            rejected += 1
        self.message_user(request, f"{rejected} submission(s) rejected.")

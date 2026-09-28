from django.contrib import admin

from .models import Event, Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "city"]
    search_fields = ["name", "district"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "venue", "starts_at", "price"]
    list_filter = ["venue"]
    search_fields = ["title", "venue__name"]
    date_hierarchy = "starts_at"

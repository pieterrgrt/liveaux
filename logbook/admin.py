from django.contrib import admin

from .models import LogEntry


@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    # Notes are personal: they are not shown in the list.
    list_display = ["user", "event", "rating", "created_at"]
    search_fields = ["user__email", "event__title"]
    autocomplete_fields = ["user", "event"]

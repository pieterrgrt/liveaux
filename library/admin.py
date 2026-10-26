from django.contrib import admin

from .models import Copy, Entry, Episode, Item, ListItem, MediaList, Play


class EpisodeInline(admin.TabularInline):
    model = Episode
    extra = 0


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ["title", "media_type", "year", "source", "creator"]
    list_filter = ["media_type", "source"]
    search_fields = ["title", "original_title", "creator", "source_id"]
    readonly_fields = ["created_at", "refreshed_at"]
    inlines = [EpisodeInline]


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ["item", "user", "status", "score", "progress", "updated_at"]
    list_filter = ["status", "item__media_type"]
    search_fields = ["item__title", "user__email"]
    autocomplete_fields = ["item", "user"]


@admin.register(Play)
class PlayAdmin(admin.ModelAdmin):
    list_display = ["item", "episode", "user", "played_at", "minutes", "via"]
    list_filter = ["via", "item__media_type"]
    search_fields = ["item__title", "user__email"]
    autocomplete_fields = ["item", "user"]
    raw_id_fields = ["episode"]
    date_hierarchy = "played_at"


class ListItemInline(admin.TabularInline):
    model = ListItem
    extra = 0
    autocomplete_fields = ["item"]


@admin.register(MediaList)
class MediaListAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "is_public", "is_smart", "updated_at"]
    list_filter = ["is_public", "is_smart"]
    search_fields = ["name", "user__email"]
    inlines = [ListItemInline]


@admin.register(Copy)
class CopyAdmin(admin.ModelAdmin):
    list_display = ["item", "user", "format", "resolution", "acquired_on"]
    list_filter = ["format"]
    autocomplete_fields = ["item", "user"]

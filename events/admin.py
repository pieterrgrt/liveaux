from django.contrib import admin

from .models import Artist, ArtistMember, Event, Promoter, PromoterMember, Venue, VenueMember


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


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "district", "city"]
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
    list_display = ["title", "venue", "promoter", "starts_at", "price"]
    list_filter = ["venue"]
    search_fields = ["title", "venue__name"]
    date_hierarchy = "starts_at"
    autocomplete_fields = ["venue", "promoter", "artists"]
    exclude = ["saved_by"]
    readonly_fields = ["created_by"]

from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.utils.text import Truncator

from .models import Comment, Like, Report, Review


def _short(text, words=16):
    return Truncator(text).words(words)


@admin.action(description="Hide from everyone but staff")
def hide_selected(modeladmin, request, queryset):
    count = queryset.update(is_hidden=True)
    Report.objects.filter(**{f"{modeladmin.model._meta.model_name}__in": queryset}, status=Report.Status.OPEN).update(
        status=Report.Status.HIDDEN, resolved_at=timezone.now(), resolved_by=request.user
    )
    messages.success(request, f"{count} hidden.")


@admin.action(description="Show again")
def show_selected(modeladmin, request, queryset):
    count = queryset.update(is_hidden=False)
    messages.success(request, f"{count} visible again.")


class CommentInline(admin.TabularInline):
    model = Comment
    fk_name = "review"
    extra = 0
    fields = ["user", "body", "is_hidden", "created_at"]
    readonly_fields = ["user", "created_at"]


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["__str__", "excerpt", "contains_spoilers", "is_hidden", "created_at"]
    list_filter = ["is_hidden", "contains_spoilers", ("item", admin.EmptyFieldListFilter)]
    search_fields = ["body", "user__email", "user__display_name", "item__title", "event__title"]
    autocomplete_fields = ["user", "item"]
    raw_id_fields = ["event"]
    readonly_fields = ["created_at", "updated_at"]
    date_hierarchy = "created_at"
    actions = [hide_selected, show_selected]
    inlines = [CommentInline]

    @admin.display(description="Review")
    def excerpt(self, obj):
        return _short(obj.body)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["user", "excerpt", "on", "is_hidden", "created_at"]
    list_filter = ["is_hidden"]
    search_fields = ["body", "user__email", "user__display_name"]
    autocomplete_fields = ["user", "item"]
    raw_id_fields = ["review", "event"]
    readonly_fields = ["created_at"]
    date_hierarchy = "created_at"
    actions = [hide_selected, show_selected]

    @admin.display(description="Comment")
    def excerpt(self, obj):
        return _short(obj.body)

    @admin.display(description="On")
    def on(self, obj):
        return obj.target


@admin.register(Like)
class LikeAdmin(admin.ModelAdmin):
    list_display = ["user", "review", "created_at"]
    search_fields = ["user__email", "review__body"]
    raw_id_fields = ["user", "review"]


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ["created_at", "what", "content", "reason", "reporter", "status"]
    list_filter = ["status"]
    search_fields = ["reason", "review__body", "comment__body"]
    raw_id_fields = ["reporter", "review", "comment", "resolved_by"]
    readonly_fields = ["created_at", "resolved_at", "resolved_by", "link"]
    actions = ["hide_content", "dismiss"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("reporter", "review__user", "comment__user")

    @admin.display(description="What")
    def what(self, obj):
        return "Review" if obj.review_id else "Comment"

    @admin.display(description="Content")
    def content(self, obj):
        target = obj.target
        hidden = " (hidden)" if target.is_hidden else ""
        return f"{target.user.public_name}: {_short(target.body, 20)}{hidden}"

    @admin.display(description="On the site")
    def link(self, obj):
        return format_html('<a href="{}">{}</a>', obj.target.get_absolute_url(), "Open")

    @admin.action(description="Hide: take the review or comment down")
    def hide_content(self, request, queryset):
        now = timezone.now()
        for report in queryset.select_related("review", "comment"):
            target = report.target
            target.is_hidden = True
            target.save(update_fields=["is_hidden"])
            # Every open report on the same thing is settled with it.
            target.reports.filter(status=Report.Status.OPEN).update(
                status=Report.Status.HIDDEN, resolved_at=now, resolved_by=request.user
            )
        messages.success(request, "Hidden. Only staff can see it now.")

    @admin.action(description="Dismiss: nothing wrong with it")
    def dismiss(self, request, queryset):
        count = queryset.filter(status=Report.Status.OPEN).update(
            status=Report.Status.DISMISSED, resolved_at=timezone.now(), resolved_by=request.user
        )
        messages.success(request, f"{count} report{'s' if count != 1 else ''} dismissed.")

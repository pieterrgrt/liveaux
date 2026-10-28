from django import template

from social import services

register = template.Library()


@register.simple_tag(takes_context=True)
def reviews_for(context, target):
    """`{% reviews_for item as s %}`: averages, reviews, your own and the comments on one item or event."""
    return services.reviews_block(context["request"], target)


@register.simple_tag
def latest_reviews(kind, limit=6):
    """`{% latest_reviews "event" as reviews %}`: the newest public reviews of events or items."""
    return services.latest(kind, limit)


@register.simple_tag(takes_context=True)
def absolute(context, path):
    """A full URL for a path, for link previews."""
    if not path:
        return ""
    return context["request"].build_absolute_uri(path)

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),
    path("account/", include("allauth.urls")),
    path("", include("logbook.urls")),
    path("", include("library.urls")),
    path("me/", include("accounts.urls")),
    path(
        "privacy/",
        TemplateView.as_view(template_name="privacy.html", extra_context={"contact_email": settings.CONTACT_EMAIL}),
        name="privacy",
    ),
    path("", include("events.urls")),
]

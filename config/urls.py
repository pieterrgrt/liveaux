"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
from django.views.generic import TemplateView
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("account/", include("allauth.urls")),
    path("", include("logbook.urls")),
    path("me/", include("accounts.urls")),
    path(
        "privacy/",
        TemplateView.as_view(template_name="privacy.html", extra_context={"contact_email": settings.CONTACT_EMAIL}),
        name="privacy",
    ),
    path("", include("events.urls")),
]

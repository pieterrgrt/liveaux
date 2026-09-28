from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("delete/", views.delete_account, name="delete"),
    path("export/", views.export_data, name="export"),
]

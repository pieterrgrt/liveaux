from django.urls import path

from . import views

app_name = "logbook"

urlpatterns = [
    path("events/<int:pk>/attended/", views.attended, name="attended"),
    path("me/log/", views.mine, name="mine"),
    path("me/log/<int:year>/", views.my_year, name="my_year"),
    path("me/log/entries/<int:pk>/", views.edit, name="edit"),
    path("me/log/entries/<int:pk>/delete/", views.delete, name="delete"),
    path("people/<int:pk>/", views.public, name="public"),
    path("people/<int:pk>/<int:year>/", views.public_year, name="public_year"),
]

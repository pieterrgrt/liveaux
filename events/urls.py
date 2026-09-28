from django.urls import path

from . import views, views_manage

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("week/", views.this_week, name="this_week"),
    path("week/<slug:slug>/", views.city_week, name="city_week"),
    path("submit/", views.submit_event, name="submit_event"),
    path("events/<int:pk>/", views.event_detail, name="event_detail"),
    path("events/<int:pk>/save/", views.toggle_save, name="toggle_save"),
    path("venues/<int:pk>/", views.page_detail, {"kind": "venue"}, name="venue_detail"),
    path("promoters/<int:pk>/", views.page_detail, {"kind": "promoter"}, name="promoter_detail"),
    path("artists/<int:pk>/", views.page_detail, {"kind": "artist"}, name="artist_detail"),
    path("follow/<str:kind>/<int:pk>/", views.toggle_follow, name="toggle_follow"),
    # Managing pages and events. Event routes come first: "events" would otherwise match <str:kind>.
    path("manage/events/<int:pk>/edit/", views_manage.edit_event, name="edit_event"),
    path("manage/events/<int:pk>/delete/", views_manage.delete_event, name="delete_event"),
    path("manage/new/<str:kind>/", views_manage.create_page, name="create_page"),
    path("manage/<str:kind>/<int:pk>/", views_manage.manage_page, name="manage_page"),
    path("manage/<str:kind>/<int:pk>/edit/", views_manage.edit_page, name="edit_page"),
    path("manage/<str:kind>/<int:pk>/members/add/", views_manage.add_member, name="add_member"),
    path(
        "manage/<str:kind>/<int:pk>/members/<int:membership_pk>/remove/",
        views_manage.remove_member,
        name="remove_member",
    ),
    path("manage/<str:kind>/<int:pk>/events/new/", views_manage.create_event, name="create_event"),
]

from django.urls import path

from . import views

app_name = "social"

urlpatterns = [
    path("reviews/<int:pk>/", views.review_detail, name="review"),
    path("reviews/<int:pk>/delete/", views.delete_review, name="delete_review"),
    path("reviews/<int:pk>/like/", views.like, name="like"),
    path("reviews/write/<str:kind>/<int:pk>/", views.write_review, name="write_review"),
    path("comments/on/<str:kind>/<int:pk>/", views.add_comment, name="add_comment"),
    path("comments/<int:pk>/delete/", views.delete_comment, name="delete_comment"),
    path("moderate/<str:kind>/<int:pk>/hide/", views.hide, name="hide"),
    path("report/<str:kind>/<int:pk>/", views.report, name="report"),
    path("people/<int:pk>/reviews/", views.person, name="person"),
]

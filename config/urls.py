from django.contrib import admin

from django.urls import include, path

from interviews import views


urlpatterns = [

    path("admin/", admin.site.urls),

    path(
        "interview/",
        include("interviews.urls"),
    ),

    path(
        "",
        views.home,
        name="home",
    ),

]
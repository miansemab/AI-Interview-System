from django.urls import path

from . import views


app_name = "interviews"


urlpatterns = [
    path(
        "",
        views.start_interview,
        name="start_interview",
    ),

    path(
        "room/<int:session_id>/",
        views.interview_room,
        name="interview_room",
    ),
    path(
        "room/<int:session_id>/speaker-enrollment/",
        views.speaker_enrollment,
        name="speaker_enrollment",
    ),
    path(
        "room/<int:session_id>/speaker-recheck/",
        views.speaker_recheck,
        name="speaker_recheck",
    ),
    path(
        "room/<int:session_id>/speaker-data/delete/",
        views.delete_speaker_data,
        name="delete_speaker_data",
    ),

    path(
        "room/<int:session_id>/submit/",
        views.submit_answer,
        name="submit_answer",
    ),

    path(
        "room/<int:session_id>/finish/",
        views.finish_interview,
        name="finish_interview",
    ),
    path(
        "report/<int:session_id>/",
        views.interview_report,
        name="interview_report",
    ),
]

from django.contrib import admin

from .models import (
    Question,
    InterviewSession,
    InterviewQuestion,
    Answer,
    Evaluation,
    FinalAssessment,
)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "question_id",
        "skill",
        "topic",
        "difficulty",
        "question_type",
        "is_active",
    )

    list_filter = (
        "difficulty",
        "question_type",
        "skill",
        "is_active",
    )

    search_fields = (
        "question_id",
        "question",
        "skill__name",
        "topic__name",
    )


@admin.register(InterviewSession)
class InterviewSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "candidate_name",
        "role",
        "status",
        "current_difficulty",
        "created_at",
    )

    list_filter = (
        "status",
        "role",
        "current_difficulty",
    )

    search_fields = (
        "candidate_name",
        "candidate_email",
    )


@admin.register(InterviewQuestion)
class InterviewQuestionAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "question",
        "order",
        "asked_at",
    )


@admin.register(Answer)
class AnswerAdmin(admin.ModelAdmin):
    list_display = (
        "interview_question",
        "answer_duration_seconds",
        "created_at",
    )


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = (
        "answer",
        "total_score",
        "confidence",
        "follow_up_required",
        "created_at",
    )


@admin.register(FinalAssessment)
class FinalAssessmentAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "overall_score",
        "skill_level",
        "created_at",
    )
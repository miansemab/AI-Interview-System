from django.db import models

from roles.models import Role, Skill, Topic


class Question(models.Model):

    DIFFICULTY_CHOICES = [
        ("beginner", "Beginner"),
        ("intermediate", "Intermediate"),
        ("advanced", "Advanced"),
    ]

    TYPE_CHOICES = [
        ("conceptual", "Conceptual"),
        ("practical", "Practical"),
        ("scenario", "Scenario"),
        ("problem_solving", "Problem Solving"),
        ("debugging", "Debugging"),
        ("introduction", "Introduction"),
    ]

    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="questions",
    )

    question_id = models.CharField(
        max_length=100,
        unique=True,
    )

    question = models.TextField()

    difficulty = models.CharField(
        max_length=20,
        choices=DIFFICULTY_CHOICES,
    )

    question_type = models.CharField(
        max_length=30,
        choices=TYPE_CHOICES,
    )

    expected_concepts = models.JSONField(default=list)
    keywords = models.JSONField(default=list)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["skill", "difficulty"]

    def __str__(self):
        return self.question


class InterviewSession(models.Model):

    STATUS_CHOICES = [
        ("created", "Created"),
        ("in_progress", "In Progress"),
        ("speaker_paused", "Paused for Speaker Verification"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="interview_sessions",
    )

    candidate_name = models.CharField(
        max_length=150,
        blank=True,
    )

    candidate_email = models.EmailField(
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="created",
    )

    environment_snapshot = models.JSONField(default=dict)

    current_difficulty = models.CharField(
        max_length=20,
        default="beginner",
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate_name or 'Candidate'} - {self.role.name}"


class InterviewQuestion(models.Model):

    session = models.ForeignKey(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="interview_questions",
    )

    question = models.ForeignKey(
        Question,
        on_delete=models.PROTECT,
        related_name="session_questions",
    )

    order = models.PositiveIntegerField()

    asked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]
        unique_together = [
            ("session", "order"),
        ]

    def __str__(self):
        return f"{self.session} - Q{self.order}"


class Answer(models.Model):

    interview_question = models.OneToOneField(
        InterviewQuestion,
        on_delete=models.CASCADE,
        related_name="answer",
    )

    audio_file = models.FileField(
        upload_to="interviews/audio/",
        blank=True,
        null=True,
    )

    transcript = models.TextField(blank=True)

    transcript_data = models.JSONField(default=dict)

    answer_duration_seconds = models.FloatField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Answer - {self.interview_question}"


class Evaluation(models.Model):

    answer = models.OneToOneField(
        Answer,
        on_delete=models.CASCADE,
        related_name="evaluation",
    )

    technical_accuracy = models.FloatField(default=0)
    conceptual_understanding = models.FloatField(default=0)
    practical_application = models.FloatField(default=0)
    problem_solving = models.FloatField(default=0)
    communication = models.FloatField(default=0)

    total_score = models.FloatField(default=0)

    confidence = models.FloatField(default=0)

    strengths = models.JSONField(default=list)
    weaknesses = models.JSONField(default=list)
    missing_concepts = models.JSONField(default=list)

    follow_up_required = models.BooleanField(default=False)

    recommended_difficulty = models.CharField(
        max_length=20,
        blank=True,
    )

    ai_feedback = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Evaluation - {self.answer.interview_question}"


class FinalAssessment(models.Model):

    session = models.OneToOneField(
        InterviewSession,
        on_delete=models.CASCADE,
        related_name="final_assessment",
    )

    overall_score = models.FloatField(default=0)

    skill_level = models.CharField(
        max_length=50,
        blank=True,
    )

    skill_scores = models.JSONField(default=dict)

    strong_skills = models.JSONField(default=list)
    weak_skills = models.JSONField(default=list)
    missing_concepts = models.JSONField(default=list)

    training_needs = models.JSONField(default=list)
    recommended_topics = models.JSONField(default=list)

    interview_summary = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Assessment - {self.session}"

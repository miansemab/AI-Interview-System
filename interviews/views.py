import time

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from roles.models import Role

from .models import InterviewSession, InterviewQuestion, Answer, Evaluation, FinalAssessment
from .question_engine import QuestionEngine
from .evaluation_engine import AnswerEvaluator
from .final_assessment_engine import FinalAssessmentEngine
from .speaker_verification import (
    AudioSampleError,
    compare_sample,
    enroll_samples,
)


VOICE_ACCESS_SESSION_KEY = "interview_voice_access"


def grant_interview_access(request, session):
    ids = set(request.session.get(VOICE_ACCESS_SESSION_KEY, []))
    ids.add(str(session.id))
    request.session[VOICE_ACCESS_SESSION_KEY] = sorted(ids)


def has_interview_access(request, session):
    return str(session.id) in request.session.get(VOICE_ACCESS_SESSION_KEY, [])


def speaker_profile_key(session):
    return f"interview-speaker-profile:{session.id}"


def store_speaker_profile(session, profile):
    """Update ephemeral state without extending its original retention window."""
    expires_at = profile.get("expires_at")
    if expires_at is None:
        expires_at = time.time() + settings.SPEAKER_PROFILE_CACHE_SECONDS
        profile["expires_at"] = expires_at
    remaining = expires_at - time.time()
    if remaining <= 0:
        cache.delete(speaker_profile_key(session))
        return False
    cache.set(speaker_profile_key(session), profile, max(1, int(remaining)))
    return True


def speaker_error(message, status=422):
    return JsonResponse({"error": message}, status=status)


def ensure_final_assessment(session):
    """Return the session's existing assessment or create it from evaluations."""
    assessment = getattr(session, "final_assessment", None)
    if assessment is None and Evaluation.objects.filter(
        answer__interview_question__session=session,
    ).exists():
        assessment = FinalAssessmentEngine(session).generate()
    return assessment


def render_interview_complete(request, session):
    """Render a session's assessment and a review of its saved evaluations."""
    # Rendering a report is read-only: completion paths save assessments before
    # redirecting here, while historical sessions may legitimately lack one.
    assessment = getattr(session, "final_assessment", None)

    reviews = list(
        InterviewQuestion.objects.filter(session=session)
        .select_related("question", "question__skill", "answer")
        .prefetch_related("answer__evaluation")
        .order_by("order")
    )
    evaluated_count = 0
    correct_count = 0
    partial_count = 0
    incorrect_count = 0
    communication_total = 0.0
    for item in reviews:
        evaluation = getattr(getattr(item, "answer", None), "evaluation", None)
        item.evaluation = evaluation
        item.planned_placeholder = False
        if evaluation is None:
            has_answer = hasattr(item, "answer")
            item.evaluation_status = "Submitted but not evaluated" if has_answer else "Unanswered"
            item.status_class = "submitted-not-evaluated" if has_answer else "unanswered"
            continue
        evaluated_count += 1
        communication_total += evaluation.communication
        # The answer evaluator and feedback use 80 and 60 as the strong,
        # reasonable, and developing performance bands respectively.
        if evaluation.total_score >= 80:
            correct_count += 1
            item.evaluation_status = "Correct"
            item.status_class = "correct"
        elif evaluation.total_score >= 60:
            partial_count += 1
            item.evaluation_status = "Partially correct"
            item.status_class = "partial"
        else:
            incorrect_count += 1
            item.evaluation_status = "Incorrect"
            item.status_class = "incorrect"

    total_question_count = QuestionEngine(session).get_question_limit()
    attempted_question_count = Answer.objects.filter(
        interview_question__session=session,
    ).count()
    submitted_not_evaluated_count = max(attempted_question_count - evaluated_count, 0)
    unanswered_count = max(total_question_count - attempted_question_count, 0)
    asked_question_count = len(reviews)
    next_order = max((item.order for item in reviews), default=0) + 1
    for order in range(next_order, next_order + max(total_question_count - len(reviews), 0)):
        reviews.append({
            "order": order,
            "planned_placeholder": True,
            "evaluation_status": "Unanswered",
            "status_class": "unanswered",
        })

    completion_type = "Completed early" if asked_question_count < total_question_count else "Completed"
    coverage_percent = round(evaluated_count / total_question_count * 100) if total_question_count else 0
    communication_score = round(communication_total / evaluated_count, 1) if evaluated_count else None

    missing_concepts = (assessment.missing_concepts or []) if assessment else []
    if not isinstance(missing_concepts, list):
        missing_concepts = []
    skill_scores = (assessment.skill_scores or {}) if assessment else {}
    study_plan = []

    def skill_score_for_sort(item):
        data = item[1]
        if not isinstance(data, dict):
            return 0
        try:
            return float(data.get("score", 0))
        except (TypeError, ValueError):
            return 0

    for skill_name, data in sorted(
        skill_scores.items(),
        key=skill_score_for_sort,
    ):
        if not isinstance(data, dict) or data.get("score") is None:
            continue
        score = data["score"]
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        if score < 70:
            study_plan.append({
                "title": f"Review {skill_name}",
                "detail": f"Suggested exercise: explain one core idea, then work through a small practical example. Saved skill score: {score:.1f}/100.",
            })
    for concept in missing_concepts[:5]:
        study_plan.append({
            "title": f"Review {concept}",
            "detail": "Suggested exercise: write a short definition and give one practical example before revisiting a related question.",
        })

    coaching_suggestions = [
        "Try a brief pause, then organize an answer as definition, example, and benefit.",
        "Support technical explanations with a concrete example when the question calls for one.",
    ]
    coaching_suggestions.extend(f"Review the concept “{concept}” from the saved evaluation feedback." for concept in missing_concepts[:3])
    if evaluated_count < total_question_count:
        coaching_suggestions.append("Complete more questions in a future interview before drawing strong conclusions from this sample.")

    return render(
        request,
        "interviews/interview_complete.html",
        {
            "session": session,
            "assessment": assessment,
            "report_date": session.completed_at or session.created_at,
            "attempted_question_count": attempted_question_count,
            "asked_question_count": asked_question_count,
            "submitted_not_evaluated_count": submitted_not_evaluated_count,
            "total_question_count": total_question_count,
            "evaluated_question_count": evaluated_count,
            "correct_count": correct_count,
            "partial_count": partial_count,
            "incorrect_count": incorrect_count,
            "unanswered_count": unanswered_count,
            "coverage_percent": coverage_percent,
            "completion_type": completion_type,
            "question_reviews": reviews,
            "communication_score": communication_score,
            "study_plan": study_plan,
            "coaching_suggestions": coaching_suggestions,
            "confidence_assessment": {
                "label": "Insufficient data",
                "explanation": (
                    "No confidence self-report was collected. Technical scores "
                    "and speaker checks do not measure how confident you felt."
                ),
            },
        },
    )


def mark_interview_completed(session):
    """Mark a session complete once, without changing completed history."""
    if session.status != "completed":
        session.status = "completed"
        session.completed_at = timezone.now()
        session.save(update_fields=["status", "completed_at"])


def home(request):
    return render(
        request,
        "interviews/home.html",
    )


def start_interview(request):
    roles = Role.objects.filter(is_active=True)

    if request.method == "POST":
        role_id = request.POST.get("role")

        candidate_name = request.POST.get(
            "candidate_name", ""
        ).strip()

        candidate_email = request.POST.get(
            "candidate_email", ""
        ).strip()

        if not role_id:
            return render(
                request,
                "interviews/start_interview.html",
                {
                    "roles": roles,
                    "error": "Please select a job role.",
                },
            )

        if not candidate_name:
            return render(
                request,
                "interviews/start_interview.html",
                {
                    "roles": roles,
                    "error": "Please enter candidate name.",
                },
            )

        role = get_object_or_404(
            Role,
            id=role_id,
            is_active=True,
        )

        session = InterviewSession.objects.create(
            role=role,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            status="in_progress",
            environment_snapshot=role.environment,
        )

        grant_interview_access(request, session)

        return redirect(
            "interviews:speaker_enrollment",
            session_id=session.id,
        )

    return render(
        request,
        "interviews/start_interview.html",
        {
            "roles": roles,
        },
    )


def interview_room(request, session_id):
    session = get_object_or_404(
        InterviewSession.objects.select_related("role"),
        id=session_id,
    )

    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")

    if session.status == "cancelled":
        return redirect("interviews:start_interview")

    # If the interview is already completed, show its assessment.
    if session.status == "completed":
        return redirect("interviews:interview_report", session_id=session.id)

    if session.status == "speaker_paused":
        current_question = (
            session.interview_questions.select_related("question", "question__skill", "question__topic")
            .filter(answer__isnull=True)
            .order_by("-order")
            .first()
        )
        return render(
            request,
            "interviews/interview_room.html",
            {"session": session, "current_question": current_question, "verification_paused": True},
        )

    if cache.get(speaker_profile_key(session)) is None:
        return redirect("interviews:speaker_enrollment", session_id=session.id)

    engine = QuestionEngine(session)

    # Find the current unanswered question.
    current_question = (
        session.interview_questions
        .select_related(
            "question",
            "question__skill",
            "question__topic",
        )
        .filter(answer__isnull=True)
        .order_by("-order")
        .first()
    )

    # Create a question if no unanswered question exists.
    if current_question is None:
        current_question = engine.create_next_question()

    # No questions remain: complete the interview.
    if current_question is None:
        mark_interview_completed(session)

        return render_interview_complete(request, session)

    question_limit = engine.get_question_limit()
    return render(
        request,
        "interviews/interview_room.html",
        {
            "session": session,
            "current_question": current_question,
            "answered_count": Answer.objects.filter(
                interview_question__session=session,
            ).count(),
            "question_limit": question_limit,
            "progress_percent": min(
                100,
                round(current_question.order / max(question_limit, 1) * 100),
            ),
        },
    )


def submit_answer(request, session_id):
    session = get_object_or_404(
        InterviewSession.objects.select_related("role"),
        id=session_id,
    )

    # Only POST requests can submit answers.
    if request.method != "POST":
        return redirect(
            "interviews:interview_room",
            session_id=session.id,
        )

    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")

    # Prevent further answers after completion.
    if session.status == "completed":
        return redirect("interviews:interview_report", session_id=session.id)

    if session.status == "speaker_paused":
        return speaker_error(
            "DANGER — Speaker mismatch detected. The interview has been paused because the speaker could not be verified.",
            status=423,
        )

    if session.status != "in_progress":
        return speaker_error("This interview is not accepting answers.", status=409)

    profile = cache.get(speaker_profile_key(session))
    if profile is None:
        return speaker_error("Voice enrollment is missing or expired. Please enroll again before answering.", status=409)

    interview_question_id = request.POST.get("interview_question_id")
    transcript = request.POST.get("answer", "").strip()
    answer_source = request.POST.get("answer_source", "text")

    # The submitted source is descriptive metadata, not trusted input.
    if answer_source not in {"text", "voice"}:
        answer_source = "text"

    # Do not save empty answers.
    if not transcript:
        return redirect(
            "interviews:interview_room",
            session_id=session.id,
        )

    uploaded_audio = request.FILES.get("speaker_audio")
    if getattr(request, "speaker_audio_too_large", False):
        return speaker_error("The recording is too large. Please record again.", status=413)
    if uploaded_audio is None and answer_source == "voice":
        return speaker_error(
            "This request was marked as a voice answer but included no captured voice sample. Retry voice input, or edit/type the answer and submit it without speaker verification."
        )
    speaker_verification = "not_performed_text" if uploaded_audio is None else "verified"
    if uploaded_audio is not None:
        try:
            similarity = compare_sample(uploaded_audio, profile["embedding"])
        except AudioSampleError as error:
            return speaker_error(str(error))
        except Exception:
            return speaker_error("Speaker verification is temporarily unavailable. Your answer was not submitted.", status=503)

        if similarity < settings.SPEAKER_VERIFICATION_THRESHOLD:
            profile["consecutive_mismatches"] = profile.get("consecutive_mismatches", 0) + 1
            mismatch_count = profile["consecutive_mismatches"]
            store_speaker_profile(session, profile)
            if mismatch_count >= settings.SPEAKER_MISMATCH_LIMIT:
                session.status = "speaker_paused"
                session.save(update_fields=["status"])
                return speaker_error(
                    "DANGER — Speaker mismatch detected. The interview has been paused because the speaker could not be verified.",
                    status=423,
                )
            return speaker_error(
                "This voice sample did not match the enrolled reference strongly enough. Please record a clear sample from your answer and retry.",
                status=409,
            )

        profile["consecutive_mismatches"] = 0
        store_speaker_profile(session, profile)

    # Ensure the question belongs to this interview session.
    interview_question = get_object_or_404(
        session.interview_questions,
        id=interview_question_id,
    )

    # A repeated request for an already answered question must not overwrite
    # the answer or run the evaluator a second time.
    if Answer.objects.filter(interview_question=interview_question).exists():
        return redirect(
            "interviews:interview_room",
            session_id=session.id,
        )

    # Save the candidate's first submitted answer for this question.
    answer = Answer.objects.create(
        interview_question=interview_question,
        transcript=transcript,
        transcript_data={
            "source": answer_source,
            "speaker_verification": speaker_verification,
        },
    )

    # Evaluate the submitted answer.
    evaluation = AnswerEvaluator(answer).evaluate()

    # Update adaptive interview difficulty.
    engine = QuestionEngine(session)
    engine.update_difficulty(evaluation.total_score)

    # Generate the next question.
    next_question = engine.create_next_question()

    # If no more questions remain, generate the final assessment.
    if next_question is None:
        ensure_final_assessment(session)
        mark_interview_completed(session)
        cache.delete(speaker_profile_key(session))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({
                "completed": True,
                "redirect": reverse("interviews:interview_report", args=[session.id]),
            })
        return redirect("interviews:interview_report", session_id=session.id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        question = next_question.question
        question_limit = engine.get_question_limit()
        answered_count = Answer.objects.filter(interview_question__session=session).count()
        return JsonResponse({
            "completed": False,
            "redirect": reverse("interviews:interview_room", args=[session.id]),
            "question": {
                "id": next_question.id,
                "order": next_question.order,
                "text": question.question,
                "skill": question.skill.name,
                "topic": question.topic.name,
                "difficulty": question.difficulty.title(),
            },
            "answered_count": answered_count,
            "question_limit": question_limit,
            "progress_percent": min(100, round(next_question.order / max(question_limit, 1) * 100)),
        })

    # Otherwise, continue the interview.
    return redirect(
        "interviews:interview_room",
        session_id=session.id,
    )


def finish_interview(request, session_id):
    """Finish after at least one saved answer and report only saved evaluations."""
    session = get_object_or_404(
        InterviewSession.objects.select_related("role"),
        id=session_id,
    )

    if request.method != "POST":
        return redirect(
            "interviews:interview_room",
            session_id=session.id,
        )

    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")

    if request.POST.get("answer", "").strip():
        return JsonResponse(
            {"error": "Submit your current answer before finishing; it has not been discarded."},
            status=400,
        )

    if session.status == "completed":
        return redirect("interviews:interview_report", session_id=session.id)

    if session.status != "in_progress":
        return redirect(
            "interviews:interview_room",
            session_id=session.id,
        )

    if not Answer.objects.filter(interview_question__session=session).exists():
        return JsonResponse(
            {"error": "Submit and evaluate at least one answer before finishing."},
            status=400,
        )

    if not Evaluation.objects.filter(answer__interview_question__session=session).exists():
        return JsonResponse(
            {"error": "Submit and evaluate at least one answer before finishing."},
            status=400,
        )

    ensure_final_assessment(session)
    mark_interview_completed(session)
    cache.delete(speaker_profile_key(session))
    return redirect("interviews:interview_report", session_id=session.id)


def speaker_enrollment(request, session_id):
    session = get_object_or_404(InterviewSession.objects.select_related("role"), id=session_id)
    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")
    if session.status == "speaker_paused":
        return speaker_error("The interview is paused. Use a speaker recheck or delete voice data to end this session.", status=423)
    if session.status != "in_progress":
        return redirect("interviews:interview_room", session_id=session.id)
    if request.method == "GET":
        return render(request, "interviews/speaker_enrollment.html", {"session": session})
    if request.method != "POST":
        return speaker_error("POST required.", status=405)
    if request.POST.get("consent") != "on":
        return speaker_error("Consent is required before capturing reference voice samples.", status=400)
    if getattr(request, "speaker_audio_too_large", False):
        return speaker_error("A reference recording is too large. Please record again.", status=413)
    samples = [
        request.FILES.get("reference_sample_1"),
        request.FILES.get("reference_sample_2"),
    ]
    if any(sample is None for sample in samples):
        return speaker_error("Record two reference samples before enrolling.", status=400)
    try:
        embedding = enroll_samples(samples)
    except AudioSampleError as error:
        return speaker_error(str(error))
    except Exception:
        return speaker_error(
            "The local speaker model is unavailable. No interview has started; retry when the model is ready.",
            status=503,
        )
    store_speaker_profile(
        session,
        {"embedding": embedding, "consecutive_mismatches": 0},
    )
    return JsonResponse({"redirect": reverse("interviews:interview_room", args=[session.id])})


def speaker_recheck(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    session = get_object_or_404(InterviewSession, id=session_id)
    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")
    if session.status != "speaker_paused":
        return speaker_error("The interview is not paused for speaker verification.", status=409)
    profile = cache.get(speaker_profile_key(session))
    if profile is None:
        return speaker_error("The temporary voice reference expired. Voice data was not retained; this interview cannot be resumed.", status=410)
    sample = request.FILES.get("speaker_audio")
    if getattr(request, "speaker_audio_too_large", False):
        return speaker_error("The recording is too large. Please record again.", status=413)
    if sample is None:
        return speaker_error("Record a new voice sample to retry verification.")
    try:
        similarity = compare_sample(sample, profile["embedding"])
    except AudioSampleError as error:
        return speaker_error(str(error))
    except Exception:
        return speaker_error("Speaker verification is temporarily unavailable. The interview remains paused.", status=503)
    if similarity < settings.SPEAKER_VERIFICATION_THRESHOLD:
        return speaker_error("The voice sample is still inconclusive. Please retry in a quiet place.", status=409)
    profile["consecutive_mismatches"] = 0
    store_speaker_profile(session, profile)
    session.status = "in_progress"
    session.save(update_fields=["status"])
    return JsonResponse({"redirect": reverse("interviews:interview_room", args=[session.id])})


def delete_speaker_data(request, session_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    session = get_object_or_404(InterviewSession, id=session_id)
    if not has_interview_access(request, session):
        return HttpResponseForbidden("This interview is available only in the browser session that started it.")
    cache.delete(speaker_profile_key(session))
    if session.status == "speaker_paused":
        session.status = "cancelled"
        session.save(update_fields=["status"])
        return redirect("interviews:start_interview")
    return redirect("interviews:speaker_enrollment", session_id=session.id)


def interview_report(request, session_id):
    session = get_object_or_404(
        InterviewSession.objects.select_related("role"),
        id=session_id,
    )
    if session.status != "completed":
        return redirect("interviews:interview_room", session_id=session.id)
    return render_interview_complete(request, session)

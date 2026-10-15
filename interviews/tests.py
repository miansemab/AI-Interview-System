
import io
import math
import struct
import wave

from unittest.mock import patch

import numpy as np

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from roles.models import Role, Skill, Topic
from interviews.models import (
    Question,
    InterviewSession,
    InterviewQuestion,
    Answer,
    Evaluation,
    FinalAssessment,
)
from interviews.evaluation_engine import AnswerEvaluator
from interviews.views import VOICE_ACCESS_SESSION_KEY, speaker_profile_key
from interviews.speaker_verification import AudioSampleError, decode_wav


def make_voice_wav(duration=6, amplitude=9000, frequency=220):
    buffer = io.BytesIO()
    sample_count = int(16000 * duration)
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        frames = b"".join(
            struct.pack("<h", int(amplitude * math.sin(2 * math.pi * frequency * index / 16000)))
            for index in range(sample_count)
        )
        wav_file.writeframes(frames)
    return SimpleUploadedFile("sample.wav", buffer.getvalue(), content_type="audio/wav")


def authorize_interview(client, session):
    session_data = client.session
    ids = set(session_data.get(VOICE_ACCESS_SESSION_KEY, []))
    ids.add(str(session.id))
    session_data[VOICE_ACCESS_SESSION_KEY] = sorted(ids)
    session_data.save()


class AnswerSubmissionTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="Python Backend Developer")
        self.skill = Skill.objects.create(
            role=self.role,
            name="Python Fundamentals",
        )
        self.topic = Topic.objects.create(
            skill=self.skill,
            name="Python Operators",
        )
        self.question = Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="SUBMIT-PY-001",
            question="What is the difference between == and is?",
            difficulty="beginner",
            question_type="conceptual",
            expected_concepts=["value comparison", "object identity"],
            keywords=["==", "is"],
        )
        self.session = InterviewSession.objects.create(
            role=self.role,
            candidate_name="Submission Test Candidate",
            status="in_progress",
            environment_snapshot={"question_count": 1},
        )
        self.interview_question = InterviewQuestion.objects.create(
            session=self.session,
            question=self.question,
            order=1,
        )
        self.url = reverse(
            "interviews:submit_answer",
            args=[self.session.id],
        )
        authorize_interview(self.client, self.session)
        cache.set(speaker_profile_key(self.session), {"embedding": [1.0, 0.0], "consecutive_mismatches": 0})

    def submit_answer(self, transcript, source):
        payload = {
            "interview_question_id": self.interview_question.id,
            "answer": transcript,
            "answer_source": source,
        }
        if source == "voice":
            payload["speaker_audio"] = make_voice_wav()
        with patch("interviews.views.compare_sample", return_value=0.9):
            return self.client.post(self.url, payload)

    def assert_answer_was_evaluated(self, source, verification):
        answer = Answer.objects.get(
            interview_question=self.interview_question,
        )
        self.assertEqual(answer.transcript_data, {"source": source, "speaker_verification": verification})
        self.assertTrue(
            Evaluation.objects.filter(answer=answer).exists()
        )
        return answer

    def test_typed_answer_is_saved_and_evaluated(self):
        response = self.submit_answer(
            "The == operator compares values.",
            "text",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("interviews:interview_report", args=[self.session.id]))
        answer = self.assert_answer_was_evaluated("text", "not_performed_text")
        self.assertEqual(answer.transcript, "The == operator compares values.")
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "completed")
        self.assertTrue(FinalAssessment.objects.filter(session=self.session).exists())

    def test_submission_progresses_to_next_question_when_questions_remain(self):
        self.session.environment_snapshot = {"question_count": 2}
        self.session.save(update_fields=["environment_snapshot"])
        next_question = Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="SUBMIT-PY-002",
            question="When would you use object identity?",
            difficulty="beginner",
            question_type="conceptual",
        )

        response = self.submit_answer("The == operator compares values.", "text")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("interviews:interview_room", args=[self.session.id]))
        self.assertTrue(InterviewQuestion.objects.filter(session=self.session, question=next_question).exists())
        self.assertTrue(Evaluation.objects.filter(answer__interview_question=self.interview_question).exists())

    def test_ajax_answer_returns_next_question_without_room_navigation(self):
        self.session.environment_snapshot = {"question_count": 2}
        self.session.save(update_fields=["environment_snapshot"])
        next_question = Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="SUBMIT-PY-AJAX-002",
            question="When would you use object identity?",
            difficulty="beginner",
            question_type="conceptual",
        )

        response = self.client.post(
            self.url,
            {
                "interview_question_id": self.interview_question.id,
                "answer": "The == operator compares values.",
                "answer_source": "text",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        next_interview_question = InterviewQuestion.objects.get(session=self.session, question=next_question)
        self.assertFalse(payload["completed"])
        self.assertEqual(payload["redirect"], reverse("interviews:interview_room", args=[self.session.id]))
        self.assertEqual(payload["question"]["id"], next_interview_question.id)
        self.assertEqual(payload["question"]["order"], 2)
        self.assertEqual(payload["answered_count"], 1)
        self.assertEqual(payload["question_limit"], 2)
        self.assertTrue(Evaluation.objects.filter(answer__interview_question=self.interview_question).exists())

    def test_ajax_last_answer_returns_report_navigation_after_assessment(self):
        response = self.client.post(
            self.url,
            {
                "interview_question_id": self.interview_question.id,
                "answer": "The == operator compares values.",
                "answer_source": "text",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["completed"])
        self.assertEqual(response.json()["redirect"], reverse("interviews:interview_report", args=[self.session.id]))
        self.assertTrue(FinalAssessment.objects.filter(session=self.session).exists())
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "completed")

    def test_interview_room_renders_progress_and_live_camera_controls(self):
        response = self.client.get(reverse("interviews:interview_room", args=[self.session.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["answered_count"], 0)
        self.assertEqual(response.context["question_limit"], 1)
        self.assertContains(response, f'<form method="post" action="{self.url}" id="answerForm"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'type="submit" class="form-button answer-submit-button"')
        self.assertContains(response, 'id="candidateCamera"')
        self.assertEqual(response.content.count(b'id="candidateCamera"'), 1)
        self.assertEqual(response.content.count(b'id="answerSource"'), 1)
        self.assertContains(response, 'id="answerSubmitStatus"')
        self.assertContains(response, 'id="finishInterviewStatus"')
        self.assertContains(response, 'src="/static/interviews/js/speaker_capture.js"')
        self.assertContains(response, 'src="/static/interviews/js/app.js?v=speech-recognition-resume-20261015"')
        self.assertContains(response, "Browser speech recognition does not provide its raw audio")
        self.assertContains(response, "Typed answers are not speaker-verified")
        self.assertNotContains(response, "Record speaker sample for typed answer")
        self.assertNotContains(response, 'id="recordAnswerVoiceSample"')
        self.assertContains(response, 'id="cameraErrorDetail"')
        self.assertContains(response, "interview_room.css")

    def test_typed_answer_without_audio_is_saved_without_speaker_verification(self):
        with patch("interviews.views.compare_sample") as compare:
            response = self.client.post(
                self.url,
                {
                    "interview_question_id": self.interview_question.id,
                    "answer": "Keep this answer while I retry the sample.",
                    "answer_source": "text",
                },
            )

        self.assertEqual(response.status_code, 302)
        answer = Answer.objects.get(interview_question=self.interview_question)
        self.assertEqual(answer.transcript_data, {"source": "text", "speaker_verification": "not_performed_text"})
        self.assertTrue(Evaluation.objects.filter(answer=answer).exists())
        compare.assert_not_called()

    def test_voice_answer_without_captured_audio_is_rejected(self):
        with patch("interviews.views.compare_sample") as compare:
            response = self.client.post(self.url, {
                "interview_question_id": self.interview_question.id,
                "answer": "Spoken words with no captured audio.",
                "answer_source": "voice",
            })
        self.assertEqual(response.status_code, 422)
        self.assertIn("voice sample", response.json()["error"].lower())
        self.assertIn("marked as a voice answer", response.json()["error"])
        compare.assert_not_called()
        self.assertFalse(Answer.objects.filter(interview_question=self.interview_question).exists())

    def test_voice_transcript_is_saved_and_evaluated(self):
        response = self.submit_answer(
            "The == operator compares values.",
            "voice",
        )

        self.assertEqual(response.status_code, 302)
        answer = self.assert_answer_was_evaluated("voice", "verified")
        self.assertEqual(answer.transcript, "The == operator compares values.")

    def test_unexpected_answer_source_falls_back_to_text(self):
        response = self.submit_answer(
            "The == operator compares values.",
            "untrusted-value",
        )

        self.assertEqual(response.status_code, 302)
        self.assert_answer_was_evaluated("text", "not_performed_text")

    def test_empty_answer_does_not_create_answer_or_evaluation(self):
        response = self.submit_answer("   ", "voice")

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            Answer.objects.filter(
                interview_question=self.interview_question,
            ).exists()
        )
        self.assertFalse(
            Evaluation.objects.filter(
                answer__interview_question=self.interview_question,
            ).exists()
        )

    def test_repeated_answer_submission_does_not_overwrite_or_reevaluate(self):
        self.session.environment_snapshot = {"question_count": 2}
        self.session.save(update_fields=["environment_snapshot"])
        Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="SUBMIT-PY-002",
            question="What is object identity?",
            difficulty="beginner",
            question_type="conceptual",
        )

        self.submit_answer("First submitted answer", "text")
        self.submit_answer("Duplicate request with changed text", "text")

        answer = Answer.objects.get(interview_question=self.interview_question)
        self.assertEqual(answer.transcript, "First submitted answer")
        self.assertEqual(Evaluation.objects.filter(answer=answer).count(), 1)


class EarlyCompletionTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="Python Backend Developer")
        self.skill = Skill.objects.create(
            role=self.role,
            name="Python Fundamentals",
            weight=1,
        )
        self.topic = Topic.objects.create(
            skill=self.skill,
            name="Python Operators",
        )
        self.session = InterviewSession.objects.create(
            role=self.role,
            candidate_name="Early Finish Candidate",
            status="in_progress",
            environment_snapshot={"question_count": 15},
        )
        self.questions = []
        self.interview_questions = []
        for index in range(1, 16):
            question = Question.objects.create(
                skill=self.skill,
                topic=self.topic,
                question_id=f"EARLY-PY-{index:03d}",
                question=f"Explain Python concept {index}.",
                difficulty="beginner",
                question_type="conceptual",
                expected_concepts=["Python concept"],
                keywords=["Python"],
            )
            self.questions.append(question)
            self.interview_questions.append(
                InterviewQuestion.objects.create(
                    session=self.session,
                    question=question,
                    order=index,
                )
            )

        self.finish_url = reverse(
            "interviews:finish_interview",
            args=[self.session.id],
        )
        self.report_url = reverse(
            "interviews:interview_report",
            args=[self.session.id],
        )
        self.submit_url = reverse(
            "interviews:submit_answer",
            args=[self.session.id],
        )
        authorize_interview(self.client, self.session)
        cache.set(speaker_profile_key(self.session), {"embedding": [1.0, 0.0], "consecutive_mismatches": 0})

    def create_saved_answer(self, interview_question, total_score=80.0):
        answer = Answer.objects.create(
            interview_question=interview_question,
            transcript="A saved answer for this question.",
        )
        Evaluation.objects.create(
            answer=answer,
            technical_accuracy=total_score,
            conceptual_understanding=total_score,
            practical_application=total_score,
            problem_solving=total_score,
            communication=total_score,
            total_score=total_score,
        )
        return answer

    def test_can_finish_after_one_saved_answer_and_report_uses_saved_scores(self):
        self.create_saved_answer(self.interview_questions[0], total_score=80)

        response = self.client.post(self.finish_url)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "completed")
        self.assertRedirects(response, self.report_url)
        self.assertIsNotNone(self.session.completed_at)
        self.assertEqual(Answer.objects.filter(interview_question__session=self.session).count(), 1)
        self.assertEqual(Evaluation.objects.filter(answer__interview_question__session=self.session).count(), 1)
        assessment = FinalAssessment.objects.get(session=self.session)
        self.assertEqual(assessment.overall_score, 68.0)
        report = self.client.get(response.url)
        self.assertEqual(report.context["attempted_question_count"], 1)
        self.assertEqual(report.context["evaluated_question_count"], 1)
        self.assertEqual(report.context["total_question_count"], 15)
        self.assertEqual(report.context["confidence_assessment"]["label"], "Insufficient data")
        self.assertContains(report, "Limited assessment coverage")

    def test_cannot_finish_before_submitting_an_answer(self):
        response = self.client.post(self.finish_url)

        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "in_progress")
        self.assertFalse(FinalAssessment.objects.filter(session=self.session).exists())
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"error": "Submit and evaluate at least one answer before finishing."})

    def test_unsaved_text_is_rejected_without_discarding_or_saving_it(self):
        self.create_saved_answer(self.interview_questions[0], total_score=70)
        typed_answer = "This text has not been submitted yet."

        response = self.client.post(self.finish_url, {"answer": typed_answer})

        self.assertEqual(response.status_code, 400)
        self.assertIn("it has not been discarded", response.json()["error"])
        self.assertFalse(Answer.objects.filter(transcript=typed_answer).exists())
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "in_progress")

    def test_duplicate_finish_does_not_create_or_recalculate_assessment(self):
        self.create_saved_answer(self.interview_questions[0], total_score=72)

        first_response = self.client.post(self.finish_url)
        assessment = FinalAssessment.objects.get(session=self.session)
        first_created_at = assessment.created_at
        first_score = assessment.overall_score
        second_response = self.client.post(self.finish_url)

        assessment.refresh_from_db()
        self.assertRedirects(first_response, self.report_url)
        self.assertRedirects(second_response, self.report_url)
        self.assertEqual(FinalAssessment.objects.filter(session=self.session).count(), 1)
        self.assertEqual(assessment.created_at, first_created_at)
        self.assertEqual(assessment.overall_score, first_score)
        self.assertEqual(Evaluation.objects.filter(answer__interview_question__session=self.session).count(), 1)

    def test_normal_fifteen_question_completion_still_generates_one_report(self):
        for interview_question in self.interview_questions[:-1]:
            self.create_saved_answer(interview_question, total_score=75)

        with patch("interviews.views.compare_sample", return_value=0.9):
            response = self.client.post(
                self.submit_url,
                {
                    "interview_question_id": self.interview_questions[-1].id,
                    "answer": "The final answer is submitted.",
                    "answer_source": "text",
                    "speaker_audio": make_voice_wav(),
                },
            )

        self.session.refresh_from_db()
        self.assertRedirects(response, self.report_url)
        self.assertEqual(self.session.status, "completed")
        self.assertEqual(Answer.objects.filter(interview_question__session=self.session).count(), 15)
        self.assertEqual(Evaluation.objects.filter(answer__interview_question__session=self.session).count(), 15)
        self.assertEqual(FinalAssessment.objects.filter(session=self.session).count(), 1)
        report = self.client.get(response.url)
        self.assertEqual(report.context["attempted_question_count"], 15)
        self.assertEqual(report.context["evaluated_question_count"], 15)
        self.assertEqual(report.context["total_question_count"], 15)
        self.assertNotContains(report, "Assessment coverage is limited")

    def test_evaluation_categories_reconcile_and_exclude_other_sessions(self):
        for question, score in zip(self.interview_questions[:3], [80, 60, 59.99]):
            self.create_saved_answer(question, total_score=score)
        unevaluated = Answer.objects.create(
            interview_question=self.interview_questions[3],
            transcript="Saved but not evaluated",
        )
        foreign_session = InterviewSession.objects.create(
            role=self.role,
            status="in_progress",
        )
        foreign_question = InterviewQuestion.objects.create(
            session=foreign_session,
            question=self.questions[4],
            order=1,
        )
        self.create_saved_answer(foreign_question, total_score=95)

        self.client.post(self.finish_url)
        report = self.client.get(self.report_url)
        context = report.context
        self.assertEqual(context["evaluated_question_count"], 3)
        self.assertEqual(context["correct_count"], 1)
        self.assertEqual(context["partial_count"], 1)
        self.assertEqual(context["incorrect_count"], 1)
        self.assertEqual(context["correct_count"] + context["partial_count"] + context["incorrect_count"], context["evaluated_question_count"])
        self.assertEqual(context["unanswered_count"], 11)
        self.assertEqual(context["submitted_not_evaluated_count"], 1)
        self.assertEqual(unevaluated.transcript, "Saved but not evaluated")
        self.assertEqual(
            [item.evaluation_status for item in context["question_reviews"][:5]],
            ["Correct", "Partially correct", "Incorrect", "Submitted but not evaluated", "Unanswered"],
        )
        self.assertContains(report, "Submitted, not evaluated")
        self.assertContains(report, "Unanswered")
        self.assertContains(report, "Confidence &amp; Communication Insights")
        self.assertContains(report, "80–100")

    def test_early_report_lists_generated_unanswered_and_unasked_planned_questions(self):
        InterviewQuestion.objects.filter(session=self.session, order__gt=2).delete()
        self.create_saved_answer(self.interview_questions[0], total_score=68)
        response = self.client.post(self.finish_url)
        report = self.client.get(response.url)

        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.context["completion_type"], "Completed early")
        self.assertEqual(report.context["unanswered_count"], 14)
        self.assertEqual(len(report.context["question_reviews"]), 15)
        placeholders = [
            item for item in report.context["question_reviews"]
            if isinstance(item, dict) and item.get("planned_placeholder", False)
        ]
        self.assertEqual(len(placeholders), 13)
        self.assertContains(report, "Question not generated before this interview ended")
        self.assertContains(report, "Limited assessment coverage")

    def test_zero_evaluation_report_is_read_only_and_handles_missing_assessment(self):
        self.session.status = "completed"
        self.session.save(update_fields=["status"])

        response = self.client.get(self.report_url)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["assessment"])
        self.assertEqual(response.context["evaluated_question_count"], 0)
        self.assertEqual(response.context["unanswered_count"], 15)
        self.assertIsNone(response.context["communication_score"])
        self.assertFalse(FinalAssessment.objects.filter(session=self.session).exists())
        self.assertContains(response, "Not assessed")
        self.assertContains(response, "Insufficient data")

    def test_report_escapes_candidate_answer_and_evaluation_text(self):
        self.session.candidate_name = '<script>alert("candidate")</script>'
        self.session.save(update_fields=["candidate_name"])
        answer = self.create_saved_answer(self.interview_questions[0], total_score=80)
        answer.transcript = '<img src=x onerror="alert(1)">'
        answer.save(update_fields=["transcript"])
        evaluation = answer.evaluation
        evaluation.ai_feedback = '<script>alert("feedback")</script>'
        evaluation.save(update_fields=["ai_feedback"])
        self.client.post(self.finish_url)

        response = self.client.get(self.report_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "&lt;script&gt;")
        self.assertContains(response, "&lt;img")
        self.assertNotContains(response, '<script>alert("candidate")</script>')
        self.assertNotContains(response, '<img src=x onerror="alert(1)">')

    def test_historical_assessment_without_evaluations_remains_viewable(self):
        self.session.status = "completed"
        self.session.save(update_fields=["status"])
        FinalAssessment.objects.create(
            session=self.session,
            overall_score=64,
            skill_level="Intermediate",
            interview_summary="Historical assessment",
        )

        response = self.client.get(self.report_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Historical assessment")
        self.assertEqual(response.context["evaluated_question_count"], 0)


class SpeakerVerificationFlowTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(name="Speaker Check Role")
        self.skill = Skill.objects.create(role=self.role, name="Communication")
        self.topic = Topic.objects.create(skill=self.skill, name="Responses")
        self.questions = [
            Question.objects.create(
                skill=self.skill,
                topic=self.topic,
                question_id=f"SPEAKER-{index}",
                question=f"Describe answer {index}.",
                difficulty="beginner",
                question_type="conceptual",
                expected_concepts=["answer"],
                keywords=["answer"],
            )
            for index in (1, 2)
        ]
        self.session = InterviewSession.objects.create(
            role=self.role,
            candidate_name="Voice Candidate",
            status="in_progress",
            environment_snapshot={"question_count": 2},
        )
        self.interview_questions = [
            InterviewQuestion.objects.create(
                session=self.session,
                question=question,
                order=index,
            )
            for index, question in enumerate(self.questions, start=1)
        ]
        authorize_interview(self.client, self.session)
        self.enroll_url = reverse("interviews:speaker_enrollment", args=[self.session.id])
        self.submit_url = reverse("interviews:submit_answer", args=[self.session.id])
        self.recheck_url = reverse("interviews:speaker_recheck", args=[self.session.id])
        self.delete_url = reverse("interviews:delete_speaker_data", args=[self.session.id])
        cache.set(
            speaker_profile_key(self.session),
            {"embedding": [1.0, 0.0], "consecutive_mismatches": 0},
        )

    def enroll_post(self, first=None, second=None, consent="on"):
        return self.client.post(
            self.enroll_url,
            {
                "consent": consent,
                "reference_sample_1": first or make_voice_wav(),
                "reference_sample_2": second or make_voice_wav(frequency=260),
            },
        )

    def csrf_checked_enrollment_client(self):
        client = Client(enforce_csrf_checks=True)
        authorize_interview(client, self.session)
        response = client.get(self.enroll_url)
        self.assertEqual(response.status_code, 200)
        return client, client.cookies["csrftoken"].value

    def csrf_enrollment_payload(self, csrf_token, first=None, second=None):
        return {
            # Put the CSRF token before file parts so CSRF middleware can
            # validate it even when the bounded handler stops an oversized file.
            "csrfmiddlewaretoken": csrf_token,
            "consent": "on",
            "reference_sample_1": first or make_voice_wav(),
            "reference_sample_2": second or make_voice_wav(frequency=260),
        }

    def post_answer(self, question=None, transcript="A candidate answer"):
        return self.client.post(
            self.submit_url,
            {
                "interview_question_id": (question or self.interview_questions[0]).id,
                "answer": transcript,
                "answer_source": "text",
                "speaker_audio": make_voice_wav(),
            },
        )

    def test_successful_enrollment_accepts_checkbox_consent_value_and_keeps_only_embedding(self):
        with patch("interviews.views.enroll_samples", return_value=[0.6, 0.8]) as enroll:
            response = self.enroll_post()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], reverse("interviews:interview_room", args=[self.session.id]))
        enroll.assert_called_once()
        profile = cache.get(speaker_profile_key(self.session))
        self.assertEqual(profile["embedding"], [0.6, 0.8])
        self.assertNotIn("audio", profile)

    def test_enrollment_rejects_missing_consent(self):
        cache.delete(speaker_profile_key(self.session))
        payload = {
            "reference_sample_1": make_voice_wav(),
            "reference_sample_2": make_voice_wav(frequency=260),
        }
        with patch("interviews.views.enroll_samples") as enroll:
            response = self.client.post(self.enroll_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Consent is required before capturing reference voice samples.",
        )
        enroll.assert_not_called()
        self.assertIsNone(cache.get(speaker_profile_key(self.session)))

    def test_enrollment_rejects_non_checkbox_consent_values(self):
        for consent in ("true", "yes", "1"):
            with self.subTest(consent=consent):
                cache.delete(speaker_profile_key(self.session))
                with patch("interviews.views.enroll_samples") as enroll:
                    response = self.enroll_post(consent=consent)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["error"],
                    "Consent is required before capturing reference voice samples.",
                )
                enroll.assert_not_called()
                self.assertIsNone(cache.get(speaker_profile_key(self.session)))

    def test_upload_handler_is_installed_before_csrf_parses_enrollment_post(self):
        client, csrf_token = self.csrf_checked_enrollment_client()
        with patch("interviews.views.enroll_samples", return_value=[0.6, 0.8]) as enroll:
            response = client.post(
                self.enroll_url,
                self.csrf_enrollment_payload(csrf_token),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], reverse("interviews:interview_room", args=[self.session.id]))
        enroll.assert_called_once()

    def test_invalid_audio_is_rejected_without_creating_profile(self):
        malformed = SimpleUploadedFile("bad.wav", b"not a wave", content_type="audio/wav")
        with self.assertRaises(AudioSampleError):
            decode_wav(malformed)
        cache.delete(speaker_profile_key(self.session))
        with patch("interviews.views.enroll_samples", side_effect=AudioSampleError("The audio file is invalid. Please record again.")):
            response = self.enroll_post(first=SimpleUploadedFile("bad.wav", b"not a wave", content_type="audio/wav"))
        self.assertEqual(response.status_code, 422)
        self.assertIsNone(cache.get(speaker_profile_key(self.session)))

        noise_buffer = io.BytesIO()
        noise = np.random.default_rng(42).integers(-4000, 4001, size=16000 * 6, dtype=np.int16)
        with wave.open(noise_buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(noise.tobytes())
        noisy_upload = SimpleUploadedFile("noise.wav", noise_buffer.getvalue(), content_type="audio/wav")
        with self.assertRaisesRegex(AudioSampleError, "too noisy"):
            decode_wav(noisy_upload)

    def test_oversized_upload_is_stopped_during_multipart_parsing(self):
        client, csrf_token = self.csrf_checked_enrollment_client()
        oversized = SimpleUploadedFile(
            "large.wav",
            b"0" * 1_000_001,
            content_type="audio/wav",
        )
        response = client.post(
            self.enroll_url,
            self.csrf_enrollment_payload(csrf_token, first=oversized),
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "A reference recording is too large. Please record again.")
        self.assertIsNotNone(cache.get(speaker_profile_key(self.session)))

    def test_same_speaker_answer_is_verified_then_saved_and_evaluated(self):
        with patch("interviews.views.compare_sample", return_value=0.8):
            response = self.post_answer()
        self.assertEqual(response.status_code, 302)
        answer = Answer.objects.get(interview_question=self.interview_questions[0])
        self.assertTrue(Evaluation.objects.filter(answer=answer).exists())
        self.assertIsNone(cache.get(speaker_profile_key(self.session)))

    def test_inconclusive_sample_does_not_count_as_mismatch_or_save_answer(self):
        with patch("interviews.views.compare_sample", side_effect=AudioSampleError("The recording is too quiet to verify. Please record again.")):
            response = self.post_answer()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(cache.get(speaker_profile_key(self.session))["consecutive_mismatches"], 0)
        self.assertFalse(Answer.objects.filter(interview_question=self.interview_questions[0]).exists())

    def test_confirmed_repeated_mismatch_pauses_and_preserves_prior_evaluations(self):
        prior_answer = Answer.objects.create(
            interview_question=self.interview_questions[0],
            transcript="Previously evaluated response",
        )
        prior_evaluation = Evaluation.objects.create(answer=prior_answer, total_score=74)
        with patch("interviews.views.compare_sample", return_value=0.1):
            first = self.post_answer(self.interview_questions[1])
            second = self.post_answer(self.interview_questions[1])
        self.assertEqual(first.status_code, 409)
        self.assertEqual(second.status_code, 423)
        self.assertIn("DANGER — Speaker mismatch detected.", second.json()["error"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, "speaker_paused")
        self.assertEqual(Answer.objects.filter(interview_question__session=self.session).count(), 1)
        self.assertEqual(Evaluation.objects.get(pk=prior_evaluation.pk).total_score, 74)

    def test_submission_is_blocked_while_speaker_warning_is_active(self):
        self.session.status = "speaker_paused"
        self.session.save(update_fields=["status"])
        with patch("interviews.views.compare_sample") as compare:
            response = self.post_answer()
        self.assertEqual(response.status_code, 423)
        compare.assert_not_called()
        self.assertFalse(Answer.objects.filter(interview_question__session=self.session).exists())

    def test_successful_paused_recheck_resumes_without_touching_answers(self):
        self.session.status = "speaker_paused"
        self.session.save(update_fields=["status"])
        with patch("interviews.views.compare_sample", return_value=0.78):
            response = self.client.post(self.recheck_url, {"speaker_audio": make_voice_wav()})
        self.session.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.session.status, "in_progress")

    def test_verification_cannot_be_skipped_before_enrollment(self):
        cache.delete(speaker_profile_key(self.session))
        room = self.client.get(reverse("interviews:interview_room", args=[self.session.id]))
        response = self.post_answer()
        self.assertRedirects(room, self.enroll_url)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Answer.objects.filter(interview_question__session=self.session).exists())

    def test_audio_endpoints_require_the_starting_browser_session(self):
        other_client = self.client_class()
        response = other_client.post(self.submit_url, {"speaker_audio": make_voice_wav()})
        self.assertEqual(response.status_code, 403)

    def test_deletion_clears_ephemeral_profile_without_deleting_session_answers(self):
        previous = Answer.objects.create(
            interview_question=self.interview_questions[0],
            transcript="Keep this answer",
        )
        response = self.client.post(self.delete_url)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(cache.get(speaker_profile_key(self.session)))
        self.assertTrue(Answer.objects.filter(pk=previous.pk).exists())


class InterviewModelTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(
            name="Python Backend Developer"
        )
        self.skill = Skill.objects.create(
            role=self.role,
            name="Python Fundamentals",
        )
        self.topic = Topic.objects.create(
            skill=self.skill,
            name="Python Operators",
        )
        self.question = Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="TEST-PY-001",
            question="What is the difference between == and is?",
            difficulty="beginner",
            question_type="conceptual",
            expected_concepts=[
                "value comparison",
                "object identity",
            ],
            keywords=["==", "is"],
        )
        self.session = InterviewSession.objects.create(
            role=self.role,
            candidate_name="Test Candidate",
        )
        self.interview_question = InterviewQuestion.objects.create(
            session=self.session,
            question=self.question,
            order=1,
        )

    def test_question_stores_expected_concepts_and_keywords(self):
        self.assertEqual(
            self.question.expected_concepts,
            ["value comparison", "object identity"],
        )
        self.assertEqual(
            self.question.keywords,
            ["==", "is"],
        )
        self.assertTrue(self.question.is_active)

    def test_session_starts_with_created_status(self):
        self.assertEqual(self.session.status, "created")
        self.assertEqual(
            self.session.current_difficulty,
            "beginner",
        )

    def test_interview_question_links_session_and_question(self):
        self.assertEqual(
            self.interview_question.session,
            self.session,
        )
        self.assertEqual(
            self.interview_question.question,
            self.question,
        )
        self.assertEqual(
            self.session.interview_questions.count(),
            1,
        )

    def test_answer_and_evaluation_relationship(self):
        answer = Answer.objects.create(
            interview_question=self.interview_question,
            transcript="The == operator compares values.",
        )
        evaluation = Evaluation.objects.create(
            answer=answer,
            total_score=75,
        )

        self.assertEqual(
            answer.interview_question,
            self.interview_question,
        )
        self.assertEqual(answer.evaluation, evaluation)
        self.assertEqual(evaluation.total_score, 75)


class AnswerEvaluatorTests(TestCase):
    def setUp(self):
        self.role = Role.objects.create(
            name="Python Backend Developer"
        )
        self.skill = Skill.objects.create(
            role=self.role,
            name="Python Fundamentals",
        )
        self.topic = Topic.objects.create(
            skill=self.skill,
            name="Python Operators",
        )
        self.question = Question.objects.create(
            skill=self.skill,
            topic=self.topic,
            question_id="EVAL-PY-001",
            question=(
                "Explain the difference between == and is in Python. "
                "Give an example where using is incorrectly could cause a bug."
            ),
            difficulty="beginner",
            question_type="conceptual",
            expected_concepts=[
                "value comparison",
                "identity comparison",
                "object identity",
            ],
            keywords=["==", "is", "identity", "value"],
        )
        self.session = InterviewSession.objects.create(
            role=self.role,
            candidate_name="Evaluator Test Candidate",
        )
        self.interview_question = InterviewQuestion.objects.create(
            session=self.session,
            question=self.question,
            order=1,
        )
        self.answer = Answer.objects.create(
            interview_question=self.interview_question,
            transcript="",
        )

    def get_scores(self, transcript):
        self.answer.transcript = transcript
        evaluator = AnswerEvaluator(self.answer)
        return evaluator.calculate_scores()

    def test_reversed_answer_does_not_match_concepts_as_correct(self):
        reversed_answer = (
            "The == operator checks whether two variables refer to "
            "the same object in memory, while is compares their values."
        )

        self.answer.transcript = reversed_answer
        evaluator = AnswerEvaluator(self.answer)
        normalized = evaluator.normalize_text(reversed_answer)

        self.assertFalse(
            evaluator.concept_is_present(
                "value comparison",
                normalized,
            )
        )
        self.assertFalse(
            evaluator.concept_is_present(
                "identity comparison",
                normalized,
            )
        )


    def test_correct_answer_scores_higher_than_reversed_answer(self):
        correct_answer = (
            "The == operator compares values, while the is operator "
            "checks whether two variables refer to the same object "
            "in memory. Use == for value equality and is for "
            "object identity. For example, using is with equal large "
            "integers can cause a bug because identity is not guaranteed."
        )

        reversed_answer = (
            "The == operator checks whether two variables refer to "
            "the same object in memory, while is compares their "
            "values. They are interchangeable in Python."
        )

        correct_scores = self.get_scores(correct_answer)
        reversed_scores = self.get_scores(reversed_answer)

        self.assertGreater(
            correct_scores["total_score"],
            reversed_scores["total_score"],
        )

    def test_reversed_operator_meanings_are_detected(self):
        reversed_answer = (
            "The == operator checks whether two variables refer to "
            "the same object in memory, while is compares their values."
        )

        self.answer.transcript = reversed_answer
        evaluator = AnswerEvaluator(self.answer)

        self.assertTrue(
            evaluator.has_operator_contradiction()
        )

    def test_correct_operator_meanings_are_not_flagged(self):
        self.answer.transcript = (
            "The == operator compares values, while the is operator "
            "checks object identity."
        )
        evaluator = AnswerEvaluator(self.answer)

        self.assertFalse(evaluator.has_operator_contradiction())

    def test_valid_alternative_identity_phrasing_is_recognized(self):
        answer = (
            "The is operator checks whether two names refer to a "
            "single shared instance."
        )
        self.answer.transcript = answer
        evaluator = AnswerEvaluator(self.answer)

        self.assertTrue(
            evaluator.concept_is_present(
                "object identity",
                evaluator.normalize_text(answer),
            )
        )

    def test_similar_identity_claim_assigned_to_equality_is_not_credited(self):
        answer = (
            "The == operator checks whether two names refer to a "
            "single shared instance."
        )
        self.answer.transcript = answer
        evaluator = AnswerEvaluator(self.answer)

        self.assertFalse(
            evaluator.concept_is_present(
                "object identity",
                evaluator.normalize_text(answer),
            )
        )

    def test_empty_answer_scores_zero_for_communication(self):
        self.answer.transcript = ""
        evaluator = AnswerEvaluator(self.answer)

        self.assertEqual(
            evaluator.calculate_communication_score(),
            0.0,
        )

    def test_short_relevant_answer_does_not_earn_clear_communication(self):
        answer = "== compares values; is checks object identity."
        self.answer.transcript = answer
        evaluator = AnswerEvaluator(self.answer)
        scores = evaluator.calculate_scores()

        self.assertEqual(scores["communication"], 35.0)
        self.assertNotIn("Clear communication", evaluator.get_strengths(scores))

    def test_long_irrelevant_answer_gets_no_communication_credit(self):
        sentence = (
            "Rain falls over quiet green forests while distant birds "
            "cross open skies."
        )
        self.answer.transcript = " ".join([sentence] * 15)
        evaluator = AnswerEvaluator(self.answer)
        scores = evaluator.calculate_scores()

        self.assertEqual(scores["technical_accuracy"], 0.0)
        self.assertEqual(scores["conceptual_understanding"], 0.0)
        self.assertEqual(scores["communication"], 0.0)
        self.assertNotIn("Clear communication", evaluator.get_strengths(scores))

    def test_technically_strong_answer_can_earn_communication_credit(self):
        self.answer.transcript = (
            "The == operator compares values, while the is operator checks "
            "whether two variable names point to the same object. For example, "
            "using is with equal large integers can cause a bug because object "
            "identity is not guaranteed."
        )
        evaluator = AnswerEvaluator(self.answer)
        scores = evaluator.calculate_scores()

        self.assertGreater(scores["technical_accuracy"], 70.0)
        self.assertEqual(scores["communication"], 70.0)
        self.assertIn("Clear communication", evaluator.get_strengths(scores))

    def test_long_wrong_answer_does_not_outscore_strong_answer(self):
        strong_answer = (
            "The == operator compares values, while is checks whether "
            "two variables refer to the same object in memory. "
            "Use == for value equality and is for object identity."
        )

        long_wrong_answer = (
            "Python has many operators and variables and values are "
            "important in programming. The == operator checks object "
            "identity and whether two variables refer to the same "
            "object in memory. The is operator compares values and "
            "checks whether two values are equal. These operators are "
            "identical and can always be used interchangeably. "
            "Python developers should understand these concepts "
            "when building applications."
        )

        strong_scores = self.get_scores(strong_answer)
        wrong_scores = self.get_scores(long_wrong_answer)

        self.assertGreater(
            strong_scores["total_score"],
            wrong_scores["total_score"],
        )

    def test_reversed_operator_meanings_are_capped(self):
        reversed_answer = (
            "The == operator checks whether two variables refer to "
            "the same object in memory, while is compares their values."
        )

        self.answer.transcript = reversed_answer
        evaluator = AnswerEvaluator(self.answer)
        scores = evaluator.calculate_scores()

        self.assertTrue(
            evaluator.has_operator_contradiction()
        )
        self.assertLessEqual(
            scores["technical_accuracy"],
            30.0,
        )
        self.assertLessEqual(
            scores["conceptual_understanding"],
            30.0,
        )

    def test_mixed_answer_keeps_correctly_stated_concepts(self):
        mixed_answer = (
            "The == operator compares values, which is the value "
            "comparison. The is operator compares values too, but it "
            "checks object identity."
        )
        self.answer.transcript = mixed_answer
        evaluator = AnswerEvaluator(self.answer)
        normalized = evaluator.normalize_text(mixed_answer)

        self.assertTrue(evaluator.has_operator_contradiction())
        self.assertTrue(evaluator.concept_is_present("value comparison", normalized))
        self.assertTrue(evaluator.concept_is_present("object identity", normalized))
        self.assertGreater(evaluator.calculate_concept_score(), 30.0)

    def test_partial_answer_is_limited_for_omitting_requested_example(self):
        partial_answer = (
            "The == operator compares values. The is operator checks "
            "object identity."
        )
        scores = self.get_scores(partial_answer)
        evaluator = AnswerEvaluator(self.answer)

        self.assertFalse(evaluator.has_requested_example())
        self.assertEqual(scores["conceptual_understanding"], 100.0)
        self.assertLess(scores["practical_application"], 70.0)
        self.assertLess(scores["problem_solving"], 70.0)
        self.assertEqual(scores["total_score"], 77.25)

    def test_concrete_relevant_example_is_recognized(self):
        answer = (
            "For example, a == b can be True while a is b is False for "
            "separate lists, so using is to compare list contents can cause a bug."
        )
        self.answer.transcript = answer

        self.assertTrue(AnswerEvaluator(self.answer).has_requested_example())

    def test_irrelevant_example_marker_does_not_earn_example_credit(self):
        answer = "For example, the sky is blue."
        self.answer.transcript = answer
        evaluator = AnswerEvaluator(self.answer)
        scores = evaluator.calculate_scores()

        self.assertFalse(evaluator.has_requested_example())
        self.assertEqual(scores["technical_accuracy"], 0.0)
        self.assertEqual(scores["conceptual_understanding"], 0.0)
        self.assertEqual(scores["practical_application"], 0.0)
        self.assertEqual(scores["problem_solving"], 0.0)
        self.assertEqual(scores["communication"], 0.0)

    def test_weak_answer_scores_below_strong_answer(self):
        weak_answer = "== and is are Python operators, but I am unsure what they do."
        strong_answer = (
            "The == operator compares values, while is checks object identity. "
            "For example, using is to compare equal large integers can cause "
            "a bug because identity is not guaranteed."
        )

        self.assertLess(
            self.get_scores(weak_answer)["total_score"],
            self.get_scores(strong_answer)["total_score"],
        )

    def test_irrelevant_answer_scores_low(self):
        scores = self.get_scores(
            "I enjoy hiking and cooking with friends on weekends."
        )

        self.assertLess(scores["total_score"], 50.0)

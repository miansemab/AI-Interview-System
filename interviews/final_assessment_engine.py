
from collections import defaultdict

from .models import (
    InterviewSession,
    Evaluation,
    FinalAssessment,
)


class FinalAssessmentEngine:
    """
    Final assessment engine.

    Combines individual answer evaluations into
    a role-aware final assessment.

    Uses:
    - skill scores
    - skill weights
    - question coverage
    - missing concepts
    - strengths
    - weaknesses
    """

    def __init__(self, session: InterviewSession):
        self.session = session

    # ---------------------------------------------------------
    # GET EVALUATIONS
    # ---------------------------------------------------------

    def get_evaluations(self):

        return (
            Evaluation.objects
            .filter(
                answer__interview_question__session=self.session
            )
            .select_related(
                "answer",
                "answer__interview_question",
                "answer__interview_question__question",
                "answer__interview_question__question__skill",
            )
            .order_by(
                "answer__interview_question__order"
            )
        )

    # ---------------------------------------------------------
    # CALCULATE SKILL SCORES
    # ---------------------------------------------------------

    def calculate_skill_scores(self):

        evaluations = self.get_evaluations()

        skill_data = defaultdict(list)

        for evaluation in evaluations:

            skill = (
                evaluation
                .answer
                .interview_question
                .question
                .skill
            )

            skill_data[skill.id].append(
                evaluation
            )

        skill_scores = {}

        for skill_id, evaluation_list in skill_data.items():

            skill = (
                evaluation_list[0]
                .answer
                .interview_question
                .question
                .skill
            )

            scores = [
                evaluation.total_score
                for evaluation in evaluation_list
            ]

            average_score = (
                sum(scores) / len(scores)
            )

            question_count = len(
                evaluation_list
            )

            # -------------------------------------------------
            # COVERAGE ADJUSTMENT
            #
            # A skill assessed by only one question
            # should have lower confidence than a skill
            # assessed by several questions.
            # -------------------------------------------------

            if question_count == 1:
                coverage_factor = 0.85

            elif question_count == 2:
                coverage_factor = 0.92

            elif question_count == 3:
                coverage_factor = 0.97

            else:
                coverage_factor = 1.0

            adjusted_score = (
                average_score
                * coverage_factor
            )

            skill_scores[skill.name] = {
                "score": round(
                    adjusted_score,
                    2,
                ),
                "raw_score": round(
                    average_score,
                    2,
                ),
                "weight": skill.weight,
                "questions": question_count,
                "coverage_factor": coverage_factor,
            }

        return skill_scores

    # ---------------------------------------------------------
    # OVERALL SCORE
    # ---------------------------------------------------------

    def calculate_overall_score(
        self,
        skill_scores,
    ):

        if not skill_scores:
            return 0.0

        weighted_total = 0.0
        total_weight = 0.0

        for data in skill_scores.values():

            weighted_total += (
                data["score"]
                * data["weight"]
            )

            total_weight += data["weight"]

        if total_weight == 0:
            return 0.0

        return round(
            weighted_total / total_weight,
            2,
        )

    # ---------------------------------------------------------
    # SKILL LEVEL
    # ---------------------------------------------------------

    def get_skill_level(
        self,
        overall_score,
    ):

        if overall_score >= 80:
            return "Advanced"

        if overall_score >= 60:
            return "Intermediate"

        return "Beginner"

    # ---------------------------------------------------------
    # STRONG SKILLS
    # ---------------------------------------------------------

    def get_strong_skills(
        self,
        skill_scores,
    ):

        strong_skills = []

        for skill_name, data in skill_scores.items():

            # Require at least 2 questions
            # before calling a skill strongly demonstrated.

            if (
                data["score"] >= 70
                and data["questions"] >= 2
            ):
                strong_skills.append(
                    skill_name
                )

        return strong_skills

    # ---------------------------------------------------------
    # WEAK SKILLS
    # ---------------------------------------------------------

    def get_weak_skills(
        self,
        skill_scores,
    ):

        weak_skills = []

        for skill_name, data in skill_scores.items():

            if data["score"] < 60:

                weak_skills.append(
                    skill_name
                )

        return weak_skills

    # ---------------------------------------------------------
    # MISSING CONCEPTS
    # ---------------------------------------------------------

    def get_missing_concepts(self):

        evaluations = self.get_evaluations()

        concept_frequency = defaultdict(int)

        for evaluation in evaluations:

            concepts = (
                evaluation.missing_concepts
                or []
            )

            for concept in concepts:

                concept_frequency[
                    concept
                ] += 1

        # Sort concepts by how frequently
        # they were missing.

        sorted_concepts = sorted(
            concept_frequency.items(),
            key=lambda item: item[1],
            reverse=True,
        )

        return [
            concept
            for concept, frequency
            in sorted_concepts
        ]

    # ---------------------------------------------------------
    # TRAINING NEEDS
    # ---------------------------------------------------------

    def get_training_needs(
        self,
        skill_scores,
        missing_concepts,
    ):

        training_needs = []

        # -----------------------------------------------------
        # Skill-level recommendations
        # -----------------------------------------------------

        sorted_skills = sorted(
            skill_scores.items(),
            key=lambda item: item[1]["score"],
        )

        for skill_name, data in sorted_skills:

            if data["score"] < 50:

                training_needs.append(
                    f"Priority training required in {skill_name}"
                )

            elif data["score"] < 60:

                training_needs.append(
                    f"Improve {skill_name} fundamentals"
                )

            elif data["score"] < 70:

                training_needs.append(
                    f"Practice {skill_name} with practical exercises"
                )

        # -----------------------------------------------------
        # Missing concepts
        #
        # Only add the most frequently missing concepts.
        # -----------------------------------------------------

        for concept in missing_concepts[:5]:

            training_needs.append(
                f"Study and practice: {concept}"
            )

        return list(
            dict.fromkeys(
                training_needs
            )
        )[:8]

    # ---------------------------------------------------------
    # RECOMMENDED TOPICS
    # ---------------------------------------------------------

    def get_recommended_topics(
        self,
        skill_scores,
        missing_concepts,
    ):

        recommended_topics = []

        # Lowest-performing skills first.

        sorted_skills = sorted(
            skill_scores.items(),
            key=lambda item: item[1]["score"],
        )

        for skill_name, data in sorted_skills:

            if data["score"] < 70:

                recommended_topics.append(
                    skill_name
                )

        # Add highest-priority missing concepts.

        recommended_topics.extend(
            missing_concepts[:5]
        )

        return list(
            dict.fromkeys(
                recommended_topics
            )
        )[:8]

    # ---------------------------------------------------------
    # INTERVIEW SUMMARY
    # ---------------------------------------------------------

    def generate_summary(
        self,
        overall_score,
        skill_level,
        strong_skills,
        weak_skills,
    ):

        if overall_score >= 80:

            performance = (
                "The candidate demonstrated strong "
                "overall technical performance."
            )

        elif overall_score >= 60:

            performance = (
                "The candidate demonstrated a reasonable "
                "technical foundation with several areas "
                "that can be strengthened through practice."
            )

        else:

            performance = (
                "The candidate has a developing technical "
                "foundation and would benefit from structured "
                "training and practical exercises."
            )

        summary_parts = [
            performance,
            f"Overall score: {overall_score}/100.",
            f"Assessed skill level: {skill_level}.",
        ]

        if strong_skills:

            summary_parts.append(
                "Strong skills: "
                + ", ".join(
                    strong_skills
                )
                + "."
            )

        if weak_skills:

            summary_parts.append(
                "Priority improvement areas: "
                + ", ".join(
                    weak_skills
                )
                + "."
            )

        return " ".join(
            summary_parts
        )

    # ---------------------------------------------------------
    # GENERATE FINAL ASSESSMENT
    # ---------------------------------------------------------

    def generate(self):

        skill_scores = (
            self.calculate_skill_scores()
        )

        overall_score = (
            self.calculate_overall_score(
                skill_scores
            )
        )

        skill_level = (
            self.get_skill_level(
                overall_score
            )
        )

        strong_skills = (
            self.get_strong_skills(
                skill_scores
            )
        )

        weak_skills = (
            self.get_weak_skills(
                skill_scores
            )
        )

        missing_concepts = (
            self.get_missing_concepts()
        )

        training_needs = (
            self.get_training_needs(
                skill_scores,
                missing_concepts,
            )
        )

        recommended_topics = (
            self.get_recommended_topics(
                skill_scores,
                missing_concepts,
            )
        )

        interview_summary = (
            self.generate_summary(
                overall_score,
                skill_level,
                strong_skills,
                weak_skills,
            )
        )

        final_assessment, created = (
            FinalAssessment.objects.update_or_create(
                session=self.session,
                defaults={
                    "overall_score": overall_score,
                    "skill_level": skill_level,
                    "skill_scores": skill_scores,
                    "strong_skills": strong_skills,
                    "weak_skills": weak_skills,
                    "missing_concepts": missing_concepts,
                    "training_needs": training_needs,
                    "recommended_topics": recommended_topics,
                    "interview_summary": interview_summary,
                },
            )
        )

        return final_assessment
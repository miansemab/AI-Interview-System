import random

from .models import InterviewSession, InterviewQuestion, Question, Evaluation


class QuestionEngine:
    MAX_CONSECUTIVE_SAME_SKILL = 2

    def __init__(self, session):
        self.session = session

    def get_question_limit(self):
        environment = self.session.environment_snapshot or {}
        return int(environment.get("question_count", 15))

    def get_asked_question_ids(self):
        return list(
            InterviewQuestion.objects
            .filter(session=self.session)
            .values_list("question_id", flat=True)
        )

    def get_available_questions(self):
        asked_ids = self.get_asked_question_ids()

        return (
            Question.objects
            .filter(
                skill__role=self.session.role,
                is_active=True,
            )
            .exclude(id__in=asked_ids)
        )

    def get_next_difficulty(self, score):
        current_difficulty = self.session.current_difficulty

        if score >= 80:
            if current_difficulty == "beginner":
                return "intermediate"

            if current_difficulty == "intermediate":
                return "advanced"

            return "advanced"

        if score >= 60:
            return current_difficulty

        if current_difficulty == "advanced":
            return "intermediate"

        if current_difficulty == "intermediate":
            return "beginner"

        return "beginner"

    def update_difficulty(self, score):
        new_difficulty = self.get_next_difficulty(score)

        if self.session.current_difficulty != new_difficulty:
            self.session.current_difficulty = new_difficulty
            self.session.save(update_fields=["current_difficulty"])

        return new_difficulty

    def get_skill_scores(self):
        evaluations = (
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
        )

        skill_scores = {}

        for evaluation in evaluations:
            skill = evaluation.answer.interview_question.question.skill

            if skill.id not in skill_scores:
                skill_scores[skill.id] = {
                    "skill": skill,
                    "total_score": 0.0,
                    "questions": 0,
                    "average_score": 0.0,
                }

            skill_scores[skill.id]["total_score"] += evaluation.total_score
            skill_scores[skill.id]["questions"] += 1

        for data in skill_scores.values():
            if data["questions"] > 0:
                data["average_score"] = round(
                    data["total_score"] / data["questions"],
                    2,
                )

        return skill_scores

    def get_skill_question_counts(self):
        interview_questions = (
            InterviewQuestion.objects
            .filter(session=self.session)
            .select_related("question", "question__skill")
        )

        skill_counts = {}

        for interview_question in interview_questions:
            skill = interview_question.question.skill

            skill_counts[skill.id] = (
                skill_counts.get(skill.id, 0) + 1
            )

        return skill_counts

    def get_untested_skills(self):
        skill_counts = self.get_skill_question_counts()

        skills = self.session.role.skills.filter(
            is_active=True
        )

        return [
            skill
            for skill in skills
            if skill.id not in skill_counts
        ]

    def get_weakest_skill(self):
        skill_scores = self.get_skill_scores()

        if not skill_scores:
            return None

        weakest_skill_data = min(
            skill_scores.values(),
            key=lambda data: data["average_score"],
        )

        return weakest_skill_data["skill"]

    def get_recent_skill_ids(self, limit=2):
        recent_questions = (
            InterviewQuestion.objects
            .filter(session=self.session)
            .select_related("question", "question__skill")
            .order_by("-order")[:limit]
        )

        return [
            iq.question.skill.id
            for iq in recent_questions
        ]

    def get_consecutive_skill_count(self):
        recent_questions = list(
            InterviewQuestion.objects
            .filter(session=self.session)
            .select_related("question", "question__skill")
            .order_by("-order")[:10]
        )

        if not recent_questions:
            return 0

        latest_skill_id = recent_questions[0].question.skill.id

        count = 0

        for iq in recent_questions:
            skill_id = iq.question.skill.id

            if skill_id == latest_skill_id:
                count += 1
            else:
                break

        return count

    def get_target_skill(self, available_skills=None):
        if available_skills is None:
            skills = list(
                self.session.role.skills.filter(is_active=True)
            )
        else:
            skills = list(available_skills)

        if not skills:
            return None

        skill_counts = self.get_skill_question_counts()
        skill_scores = self.get_skill_scores()

        consecutive_count = self.get_consecutive_skill_count()

        recent_skill_ids = self.get_recent_skill_ids(limit=1)
        last_skill_id = (
            recent_skill_ids[0]
            if recent_skill_ids
            else None
        )

        # ---------------------------------------------------------
        # 1. Prevent the same skill from being selected more than
        #    MAX_CONSECUTIVE_SAME_SKILL times.
        # ---------------------------------------------------------

        if consecutive_count >= self.MAX_CONSECUTIVE_SAME_SKILL:
            alternative_skills = [
                skill
                for skill in skills
                if skill.id != last_skill_id
            ]

            if alternative_skills:
                skills = alternative_skills

        # ---------------------------------------------------------
        # 2. FIRST PRIORITY:
        #    Weak evaluated skills.
        # ---------------------------------------------------------

        evaluated_skills = []

        for skill in skills:
            if skill.id not in skill_scores:
                continue

            data = skill_scores[skill.id]

            evaluated_skills.append({
                "skill": skill,
                "average_score": data["average_score"],
                "questions": data["questions"],
                "weight": skill.weight,
            })

        if evaluated_skills:

            def weakness_priority(data):
                average_score = data["average_score"]
                weight = data["weight"]
                question_count = data["questions"]

                weakness_factor = 100 - average_score
                weight_factor = weight

                # Give less priority after repeated testing.
                coverage_factor = 1 / (question_count + 1)

                return (
                    weakness_factor * 0.60
                    + weight_factor * 0.25
                    + coverage_factor * 15
                )

            evaluated_skills.sort(
                key=weakness_priority,
                reverse=True,
            )

            highest_priority = weakness_priority(
                evaluated_skills[0]
            )

            top_candidates = [
                data
                for data in evaluated_skills
                if weakness_priority(data)
                >= highest_priority * 0.90
            ]

            selected = random.choice(top_candidates)

            return selected["skill"]

        # ---------------------------------------------------------
        # 3. SECOND PRIORITY:
        #    Untested skills.
        # ---------------------------------------------------------

        untested_skills = [
            skill
            for skill in skills
            if skill.id not in skill_counts
        ]

        if untested_skills:
            highest_weight = max(
                skill.weight
                for skill in untested_skills
            )

            top_skills = [
                skill
                for skill in untested_skills
                if skill.weight == highest_weight
            ]

            return random.choice(top_skills)

        # ---------------------------------------------------------
        # 4. FINAL FALLBACK
        # ---------------------------------------------------------

        return random.choice(skills)

    def get_difficulty_questions(self, questions):
        """
        Select questions according to the current session difficulty.

        Fallback order:
        Beginner     -> Intermediate -> Advanced
        Intermediate -> Beginner     -> Advanced
        Advanced     -> Intermediate -> Beginner

        This prevents an unexpected direct jump from Beginner
        to Advanced when the current difficulty pool is exhausted.
        """

        current_difficulty = self.session.current_difficulty

        difficulty_order = {
            "beginner": [
                "beginner",
                "intermediate",
                "advanced",
            ],
            "intermediate": [
                "intermediate",
                "beginner",
                "advanced",
            ],
            "advanced": [
                "advanced",
                "intermediate",
                "beginner",
            ],
        }

        fallback_order = difficulty_order.get(
            current_difficulty,
            [
                "beginner",
                "intermediate",
                "advanced",
            ],
        )

        for difficulty in fallback_order:
            difficulty_questions = questions.filter(
                difficulty=difficulty
            )

            if difficulty_questions.exists():
                return difficulty_questions

        return Question.objects.none()

    def get_next_question(self):
        question_limit = self.get_question_limit()

        current_count = (
            InterviewQuestion.objects
            .filter(session=self.session)
            .count()
        )

        if current_count >= question_limit:
            return None

        questions = self.get_available_questions()

        if not questions.exists():
            return None

        # ---------------------------------------------------------
        # Select the closest available difficulty level.
        # ---------------------------------------------------------

        difficulty_questions = self.get_difficulty_questions(
            questions
        )

        if not difficulty_questions.exists():
            return None

        # ---------------------------------------------------------
        # Find skills that actually have questions available at
        # the selected difficulty.
        # ---------------------------------------------------------

        available_skill_ids = set(
            difficulty_questions.values_list(
                "skill_id",
                flat=True,
            )
        )

        available_skills = self.session.role.skills.filter(
            is_active=True,
            id__in=available_skill_ids,
        )

        # ---------------------------------------------------------
        # Select target skill using:
        # - weak skill performance
        # - skill weight
        # - question coverage
        # - untested skills
        # - max consecutive skill rule
        # ---------------------------------------------------------

        target_skill = self.get_target_skill(
            available_skills=available_skills
        )

        if target_skill is not None:
            skill_questions = difficulty_questions.filter(
                skill=target_skill
            )

            if skill_questions.exists():
                question_list = list(skill_questions)

                return random.choice(question_list)

        # ---------------------------------------------------------
        # Final question fallback.
        # ---------------------------------------------------------

        question_list = list(difficulty_questions)

        if not question_list:
            return None

        return random.choice(question_list)

    def create_next_question(self):
        question = self.get_next_question()

        if question is None:
            return None

        last_question = (
            InterviewQuestion.objects
            .filter(session=self.session)
            .order_by("-order")
            .first()
        )

        if last_question:
            next_order = last_question.order + 1
        else:
            next_order = 1

        return InterviewQuestion.objects.create(
            session=self.session,
            question=question,
            order=next_order,
        )
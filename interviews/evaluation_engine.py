import re

from .models import Answer, Evaluation


class AnswerEvaluator:
    """
    Rule-based evaluation engine.

    Evaluates:
    - Technical accuracy
    - Conceptual understanding
    - Practical application
    - Problem solving
    - Communication
    - Strengths
    - Weaknesses
    - Missing concepts
    - Recommended difficulty
    - Training needs

    This version improves:
    - Concept matching with common equivalent phrases
    - Python operator keyword matching
    - Paraphrased technical concepts
    - Component-based technical concept matching
    """

    def __init__(self, answer: Answer):
        self.answer = answer
        self.question = answer.interview_question.question

    # ---------------------------------------------------------
    # TEXT NORMALIZATION
    # ---------------------------------------------------------

    def normalize_text(self, text: str) -> str:
        text = text.lower()

        text = re.sub(
            r"[^a-z0-9\s]",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    # ---------------------------------------------------------
    # OPERATOR / SYMBOL NORMALIZATION
    # ---------------------------------------------------------

    def normalize_keyword(self, keyword: str) -> str:
        """
        Normalize normal words while preserving important
        programming operators.
        """

        keyword = str(keyword).strip().lower()

        operator_map = {
            "==": " equality operator ",
            "!=": " not equal operator ",
            ">=": " greater equal operator ",
            "<=": " less equal operator ",
            ">": " greater than operator ",
            "<": " less than operator ",
            "=": " assignment operator ",
        }

        if keyword in operator_map:
            return operator_map[keyword].strip()

        return self.normalize_text(keyword)

    # ---------------------------------------------------------
    # TEXT VARIATIONS
    # ---------------------------------------------------------

    def get_concept_variations(self, concept: str) -> list[str]:
        """
        Return common equivalent phrases for technical concepts.

        This is still rule-based. It does not claim semantic
        understanding, but handles common technical paraphrases.
        """

        normalized = self.normalize_text(concept)

        variations = {
            "value comparison": [
                "value comparison",
                "compare values",
                "compares values",
                "comparing values",
                "comparison of values",
                "equal values",
                "same values",
                "values are equal",
                "checks the value",
                "check the values",
            ],

            "identity comparison": [
                "identity comparison",
                "compare identity",
                "compares identity",
                "comparing identity",
                "object identity",
                "object identity comparison",
                "checks identity",
                "check identity",
                "checks whether objects are the same",
                "checks if objects are the same",
                "checks whether two objects are the same",
                "checks if two objects are the same",
                "checks whether variables refer to the same object",
                "two variables refer to the same object",
                "variables reference the same object",
                "checks if variables refer to the same object",
            ],

            "object identity": [
                "object identity",
                "same object",
                "same objects",
                "exact same object",
                "same object in memory",
                "same objects in memory",
                "object in memory",
                "objects in memory",
                "refer to the same object",
                "refers to the same object",
                "reference to the same object",
                "same memory object",
            ],
        }

        return variations.get(
            normalized,
            [normalized],
        )

    # ---------------------------------------------------------
    # CONCEPT MATCHING
    # ---------------------------------------------------------

    def concept_is_present(
        self,
        concept: str,
        answer_text: str,
    ) -> bool:
        """
        Determine whether a concept is demonstrated.

        Matching strategy:
        1. Exact normalized phrase
        2. Known equivalent technical phrases
        3. Concept-specific component patterns
        """

        normalized_concept = self.normalize_text(concept)

        if not normalized_concept:
            return False

        # Keep operator meanings attached to their operators. Phrase-only
        # matching can otherwise award both concepts for a reversed answer.
        clauses = re.split(
            r"\b(?:while|whereas|but|and)\b|[;.!?]",
            self.answer.transcript.lower(),
        )
        clauses = [
            self.normalize_text(clause.replace("==", " equality operator "))
            for clause in clauses
        ]
        clauses = [clause for clause in clauses if clause]

        if normalized_concept in {
            "value comparison",
            "identity comparison",
            "object identity",
        }:
            for clause in clauses:
                has_equality = "equality operator" in clause
                has_identity = re.search(
                    r"\bis\s+operator\b|\bis\s+(?:for|used|checks?|tests?|compares?)\b",
                    clause,
                ) is not None

                if normalized_concept == "value comparison":
                    if has_equality and has_identity:
                        continue
                    if has_equality and re.search(
                        r"\b(?:compar\w*|check\w*|test\w*)\b.{0,35}\bvalues?\b"
                        r"|\bvalue (?:comparison|equality)\b",
                        clause,
                    ):
                        return True
                    if (
                        not has_equality
                        and not has_identity
                        and re.search(r"\bvalue comparison\b|\bvalues? are equal\b", clause)
                    ):
                        return True
                else:
                    if has_equality and has_identity:
                        continue
                    if has_identity and re.search(
                        r"\b(?:same object|object identity|identity comparison|"
                        r"refer\w* to the same object|"
                        r"refer\w* to a single shared instance|"
                        r"refer\w* to one shared object|"
                        r"point\w* to one shared object)\b",
                        clause,
                    ):
                        return True
                    if (
                        not has_equality
                        and not has_identity
                        and re.search(r"\b(?:object identity|identity comparison|same object)\b", clause)
                    ):
                        return True

            return False

        # Exact and equivalent phrase matching remains available for other
        # question concepts.
        if normalized_concept in answer_text:
            return True

        variations = self.get_concept_variations(concept)
        for variation in variations:
            normalized_variation = self.normalize_text(variation)
            if normalized_variation and normalized_variation in answer_text:
                return True

        # -----------------------------------------------------
        # 3. Concept-specific component matching
        # -----------------------------------------------------

        component_patterns = {
            "identity comparison": [
                [
                    "is operator",
                    "same object",
                ],
                [
                    "is operator",
                    "exact same object",
                ],
                [
                    "is operator",
                    "object in memory",
                ],
                [
                    "is operator",
                    "refer",
                    "same object",
                ],
                [
                    "is operator",
                    "refer",
                    "exact same object",
                ],
            ],

            "value comparison": [
                [
                    "compare",
                    "values",
                ],
                [
                    "compares",
                    "values",
                ],
                [
                    "comparison",
                    "values",
                ],
                [
                    "equal",
                    "values",
                ],
                [
                    "same",
                    "values",
                ],
            ],
        }

        patterns = component_patterns.get(
            normalized_concept,
            [],
        )

        for pattern in patterns:
            if all(self.normalize_text(part) in answer_text for part in pattern):
                return True

        return False

    # ---------------------------------------------------------
    # KEYWORD MATCHING
    # ---------------------------------------------------------

    def keyword_is_present(
        self,
        keyword: str,
        answer_text: str,
    ) -> bool:
        """
        Check whether a keyword is present.

        Programming operators such as == are converted into
        meaningful searchable phrases.
        """

        keyword = str(keyword).strip().lower()

        # -----------------------------------------------------
        # Python equality operator
        # -----------------------------------------------------

        if keyword == "==":

            equality_phrases = [
                "==",
                "equality operator",
                "equal operator",
                "compares values",
                "compare values",
                "value comparison",
            ]

            raw_answer = self.answer.transcript.lower()

            for phrase in equality_phrases:

                if phrase in raw_answer:
                    return True

            return False

        # -----------------------------------------------------
        # Python identity operator
        # -----------------------------------------------------

        if keyword == "is":

            identity_phrases = [
                "identity",
                "same object",
                "object identity",
                "identity comparison",
            ]

            padded_answer = f" {answer_text} "
            raw_answer = self.answer.transcript.lower()

            for phrase in identity_phrases:

                if phrase in padded_answer:
                    return True

            if re.search(
                r"\bis\s+(?:operator|for|used|checks?|tests?|compares?)\b"
                r"|\busing\s+is\b",
                raw_answer,
            ):
                return True

            # In an answer that names both operators, an is-expression is
            # relevant even when it is written as a short code-like example.
            if "==" in raw_answer and re.search(r"\bis\b", raw_answer):
                return True

            return False

        # -----------------------------------------------------
        # Normal keyword
        # -----------------------------------------------------

        normalized_keyword = self.normalize_text(
            keyword
        )

        if not normalized_keyword:
            return False

        if normalized_keyword in answer_text:
            return True

        return False

    # ---------------------------------------------------------
    # KEYWORD SCORE
    # ---------------------------------------------------------

    def calculate_keyword_score(self) -> float:

        answer_text = self.normalize_text(
            self.answer.transcript
        )

        keywords = self.question.keywords or []

        if not keywords:
            return 50.0

        matched = 0

        for keyword in keywords:

            if self.keyword_is_present(
                keyword,
                answer_text,
            ):
                matched += 1

        score = (
            matched / len(keywords)
        ) * 100

        return round(score, 2)

    # ---------------------------------------------------------
    # CONCEPT SCORE
    # ---------------------------------------------------------

    def calculate_concept_score(self) -> float:

        answer_text = self.normalize_text(
            self.answer.transcript
        )

        concepts = (
            self.question.expected_concepts
            or []
        )

        if not concepts:
            return 50.0

        matched = 0

        for concept in concepts:

            if self.concept_is_present(
                str(concept),
                answer_text,
            ):
                matched += 1

        score = (
            matched / len(concepts)
        ) * 100

        return round(score, 2)

    # ---------------------------------------------------------
    # COMMUNICATION SCORE
    # ---------------------------------------------------------

    def calculate_communication_score(
        self,
        keyword_score: float | None = None,
        concept_score: float | None = None,
    ) -> float:

        answer_text = self.answer.transcript.strip()

        if not answer_text:
            return 0.0

        if keyword_score is None or concept_score is None:
            keyword_score = self.calculate_keyword_score()
            concept_score = self.calculate_concept_score()

            if self.has_operator_contradiction():
                keyword_score = min(keyword_score, 30.0)

        # Word count alone is not evidence of clear communication. Require
        # at least some rubric evidence before awarding communication points.
        if keyword_score <= 0 and concept_score <= 0:
            return 0.0

        words = answer_text.split()

        word_count = len(words)

        if word_count < 10:
            return 35.0

        if word_count < 25:
            return 55.0

        if word_count < 50:
            return 70.0

        if word_count < 100:
            return 85.0

        return 95.0



    def has_operator_contradiction(self) -> bool:
        """Detect direct, incorrect claims about Python == and is."""

        answer = self.answer.transcript.lower()

        # Flag only when == is directly described as checking identity.
        equality_checks_identity = re.search(
            r"(?:==|equality operator)\s+"
            r"(?:operator\s+)?"
            r"(?:checks?|tests?|compares?)\s+"
            r"(?:whether\s+)?"
            r"(?:two variables\s+)?"
            r"(?:refer to the same object|"
            r"reference the same object|"
            r"object identity|identity)",
            answer,
        )

        # Flag only when is is directly described as comparing values.
        identity_compares_values = re.search(
            r"\bis\b\s+"
            r"(?:operator\s+)?"
            r"(?:checks?|tests?|compares?)\s+"
            r"(?:whether\s+)?"
            r"(?:their\s+|the\s+)?"
            r"values\b",
            answer,
        )

        return bool(
            equality_checks_identity
            or identity_compares_values
        )

    def has_requested_example(self) -> bool:
        """Check for an explicit illustration when the question requests one."""
        question_text = self.question.question.lower()
        if not re.search(r"\b(?:give|provide|include)\s+(?:an?\s+)?example\b", question_text):
            return True

        answer = self.answer.transcript.lower()
        has_failure_signal = re.search(
            r"\b(?:bug|unexpected|wrong result|unreliable|false|incorrectly|not guaranteed)\b",
            answer,
        )

        has_is_with_data_type = re.search(
            r"\busing\s+is\b.{0,100}\b(?:lists?|integers?|ints?|strings?|literal|variables?|singleton)\b",
            answer,
        )
        has_equality_identity_example = (
            "==" in answer
            and re.search(r"\b\w+\s+is\s+(?:not\s+)?\w+\b", answer)
            and re.search(
                r"\b(?:equal|same|lists?|integers?|ints?|strings?|objects?|values?|contents?)\b",
                answer,
            )
        )

        # For the ==/is example, require a failure cue tied to a concrete
        # identity/value example; an unrelated "for example" phrase is not enough.
        return bool(
            has_failure_signal
            and (has_is_with_data_type or has_equality_identity_example)
        )

    # ---------------------------------------------------------
    # SCORE CALCULATION
    # ---------------------------------------------------------

    def calculate_scores(self) -> dict:

        keyword_score = (
            self.calculate_keyword_score()
        )

        concept_score = (
            self.calculate_concept_score()
        )

        if self.has_operator_contradiction():
            keyword_score = min(keyword_score, 30.0)

        communication_score = self.calculate_communication_score(
            keyword_score,
            concept_score,
        )

        technical_accuracy = (
            keyword_score * 0.60
            + concept_score * 0.40
        )

        conceptual_understanding = (
            concept_score
        )

        practical_application = (
            keyword_score * 0.50
            + concept_score * 0.50
        )

        # The example requested by this question is application evidence; its
        # absence limits those dimensions without discounting correctly stated
        # concepts or relying on transcript length.
        if not self.has_requested_example():
            practical_application = min(practical_application, 60.0)
            problem_solving = min(
                concept_score * 0.70 + keyword_score * 0.30,
                60.0,
            )

        else:
            problem_solving = (
                concept_score * 0.70
                + keyword_score * 0.30
            )

        total_score = (
            technical_accuracy * 0.25
            + conceptual_understanding * 0.20
            + practical_application * 0.20
            + problem_solving * 0.20
            + communication_score * 0.15
        )

        return {
            "technical_accuracy": round(
                technical_accuracy,
                2,
            ),
            "conceptual_understanding": round(
                conceptual_understanding,
                2,
            ),
            "practical_application": round(
                practical_application,
                2,
            ),
            "problem_solving": round(
                problem_solving,
                2,
            ),
            "communication": round(
                communication_score,
                2,
            ),
            "total_score": round(
                total_score,
                2,
            ),
        }

    # ---------------------------------------------------------
    # STRENGTHS
    # ---------------------------------------------------------

    def get_strengths(
        self,
        scores: dict,
    ) -> list[str]:

        strengths = []

        if scores["technical_accuracy"] >= 70:
            strengths.append(
                "Good technical accuracy"
            )

        if scores["conceptual_understanding"] >= 70:
            strengths.append(
                "Good conceptual understanding"
            )

        if scores["practical_application"] >= 70:
            strengths.append(
                "Good practical application"
            )

        if scores["problem_solving"] >= 70:
            strengths.append(
                "Good problem-solving ability"
            )

        if scores["communication"] >= 70:
            strengths.append(
                "Clear communication"
            )

        return strengths

    # ---------------------------------------------------------
    # WEAKNESSES
    # ---------------------------------------------------------

    def get_weaknesses(
        self,
        scores: dict,
    ) -> list[str]:

        weaknesses = []

        if scores["technical_accuracy"] < 50:
            weaknesses.append(
                "Technical accuracy needs significant improvement"
            )

        elif scores["technical_accuracy"] < 70:
            weaknesses.append(
                "Technical accuracy needs improvement"
            )

        if scores["conceptual_understanding"] < 50:
            weaknesses.append(
                "Conceptual understanding needs significant improvement"
            )

        elif scores["conceptual_understanding"] < 70:
            weaknesses.append(
                "Conceptual understanding needs improvement"
            )

        if scores["practical_application"] < 50:
            weaknesses.append(
                "Practical application needs significant improvement"
            )

        elif scores["practical_application"] < 70:
            weaknesses.append(
                "Practical application needs improvement"
            )

        if scores["problem_solving"] < 50:
            weaknesses.append(
                "Problem-solving needs significant improvement"
            )

        elif scores["problem_solving"] < 70:
            weaknesses.append(
                "Problem-solving needs improvement"
            )

        if scores["communication"] < 50:
            weaknesses.append(
                "Communication needs significant improvement"
            )

        elif scores["communication"] < 70:
            weaknesses.append(
                "Communication needs improvement"
            )

        return weaknesses

    # ---------------------------------------------------------
    # MISSING CONCEPTS
    # ---------------------------------------------------------

    def get_missing_concepts(self) -> list[str]:

        answer_text = self.normalize_text(
            self.answer.transcript
        )

        concepts = (
            self.question.expected_concepts
            or []
        )

        missing = []

        for concept in concepts:

            original_concept = str(concept)

            if not self.concept_is_present(
                original_concept,
                answer_text,
            ):
                missing.append(
                    original_concept
                )

        return missing

    # ---------------------------------------------------------
    # TRAINING NEEDS
    # ---------------------------------------------------------

    def get_training_needs(
        self,
        scores: dict,
        missing_concepts: list[str],
    ) -> list[str]:

        training_needs = []

        if scores["technical_accuracy"] < 70:
            training_needs.append(
                "Improve technical accuracy"
            )

        if scores["conceptual_understanding"] < 70:
            training_needs.append(
                "Strengthen conceptual understanding"
            )

        if scores["practical_application"] < 70:
            training_needs.append(
                "Practice practical application"
            )

        if scores["problem_solving"] < 70:
            training_needs.append(
                "Practice problem-solving techniques"
            )

        if scores["communication"] < 70:
            training_needs.append(
                "Improve technical communication"
            )

        for concept in missing_concepts:

            training_needs.append(
                f"Study: {concept}"
            )

        return list(
            dict.fromkeys(training_needs)
        )

    # ---------------------------------------------------------
    # RECOMMENDED DIFFICULTY
    # ---------------------------------------------------------

    def get_recommended_difficulty(
        self,
        total_score: float,
    ) -> str:

        if total_score >= 80:
            return "advanced"

        if total_score >= 60:
            return "intermediate"

        return "beginner"

    # ---------------------------------------------------------
    # CONFIDENCE
    # ---------------------------------------------------------

    def calculate_confidence(
        self,
        scores: dict,
    ) -> float:

        score_values = [
            scores["technical_accuracy"],
            scores["conceptual_understanding"],
            scores["practical_application"],
            scores["problem_solving"],
            scores["communication"],
        ]

        average = sum(score_values) / len(
            score_values
        )

        return round(
            average,
            2,
        )

    # ---------------------------------------------------------
    # FEEDBACK
    # ---------------------------------------------------------

    def generate_feedback(
        self,
        scores: dict,
        missing_concepts: list[str],
        recommended_difficulty: str,
    ) -> str:

        total_score = scores["total_score"]

        if total_score >= 80:

            performance = (
                "The candidate demonstrated strong performance."
            )

        elif total_score >= 60:

            performance = (
                "The candidate demonstrated a reasonable understanding "
                "but has some areas that need improvement."
            )

        else:

            performance = (
                "The candidate needs further development "
                "in several areas."
            )

        feedback_parts = [
            performance,
            (
                f"Overall score: "
                f"{total_score}/100."
            ),
            (
                f"Recommended next difficulty: "
                f"{recommended_difficulty}."
            ),
        ]

        if missing_concepts:

            concepts = ", ".join(
                missing_concepts
            )

            feedback_parts.append(
                f"Important concepts not demonstrated: {concepts}."
            )

        return " ".join(
            feedback_parts
        )

    # ---------------------------------------------------------
    # MAIN EVALUATION
    # ---------------------------------------------------------

    def evaluate(self) -> Evaluation:

        scores = self.calculate_scores()

        strengths = self.get_strengths(
            scores
        )

        weaknesses = self.get_weaknesses(
            scores
        )

        missing_concepts = (
            self.get_missing_concepts()
        )

        training_needs = (
            self.get_training_needs(
                scores,
                missing_concepts,
            )
        )

        recommended_difficulty = (
            self.get_recommended_difficulty(
                scores["total_score"]
            )
        )

        confidence = (
            self.calculate_confidence(
                scores
            )
        )

        feedback = (
            self.generate_feedback(
                scores,
                missing_concepts,
                recommended_difficulty,
            )
        )

        follow_up_required = (
            scores["total_score"] < 60
            or bool(missing_concepts)
        )

        evaluation, created = (
            Evaluation.objects.update_or_create(
                answer=self.answer,
                defaults={
                    "technical_accuracy": scores[
                        "technical_accuracy"
                    ],
                    "conceptual_understanding": scores[
                        "conceptual_understanding"
                    ],
                    "practical_application": scores[
                        "practical_application"
                    ],
                    "problem_solving": scores[
                        "problem_solving"
                    ],
                    "communication": scores[
                        "communication"
                    ],
                    "total_score": scores[
                        "total_score"
                    ],
                    "confidence": confidence,
                    "strengths": strengths,
                    "weaknesses": weaknesses,
                    "missing_concepts": missing_concepts,
                    "follow_up_required": follow_up_required,
                    "recommended_difficulty": recommended_difficulty,
                    "ai_feedback": feedback,
                },
            )
        )

        return evaluation

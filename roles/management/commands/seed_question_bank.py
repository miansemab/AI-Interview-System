import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from roles.models import Role, Skill, Topic
from interviews.models import Question


class Command(BaseCommand):
    help = "Load roles, skills, topics and questions from question_bank.json"

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parents[3]
        json_path = base_dir / "data" / "question_bank.json"

        if not json_path.exists():
            self.stdout.write(
                self.style.ERROR(
                    f"Question bank not found: {json_path}"
                )
            )
            return

        try:
            with json_path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as error:
            self.stdout.write(
                self.style.ERROR(
                    f"Invalid JSON: {error}"
                )
            )
            return

        roles_data = data.get("roles", [])

        if not roles_data:
            self.stdout.write(
                self.style.ERROR(
                    "No roles found in question_bank.json"
                )
            )
            return

        total_roles = 0
        total_skills = 0
        total_topics = 0
        total_questions = 0

        with transaction.atomic():

            for role_data in roles_data:
                role, role_created = Role.objects.update_or_create(
                    name=role_data["name"],
                    defaults={
                        "category": role_data.get("category", ""),
                        "description": role_data.get("description", ""),
                        "environment": role_data.get("environment", {}),
                        "is_active": True,
                    },
                )

                if role_created:
                    total_roles += 1

                self.stdout.write(
                    f"Role: {role.name}"
                )

                for skill_data in role_data.get("skills", []):

                    skill, skill_created = Skill.objects.update_or_create(
                        role=role,
                        name=skill_data["name"],
                        defaults={
                            "category": skill_data.get("category", ""),
                            "description": skill_data.get("description", ""),
                            "weight": skill_data.get("weight", 10),
                            "is_required": skill_data.get(
                                "is_required",
                                True,
                            ),
                            "is_active": True,
                        },
                    )

                    if skill_created:
                        total_skills += 1

                    for topic_data in skill_data.get("topics", []):

                        topic, topic_created = Topic.objects.update_or_create(
                            skill=skill,
                            name=topic_data["name"],
                            defaults={
                                "description": topic_data.get(
                                    "description",
                                    "",
                                ),
                                "is_active": True,
                            },
                        )

                        if topic_created:
                            total_topics += 1

                        for question_data in topic_data.get(
                            "questions",
                            [],
                        ):

                            question, question_created = (
                                Question.objects.update_or_create(
                                    question_id=question_data["question_id"],
                                    defaults={
                                        "skill": skill,
                                        "topic": topic,
                                        "question": question_data["question"],
                                        "difficulty": question_data[
                                            "difficulty"
                                        ],
                                        "question_type": question_data[
                                            "question_type"
                                        ],
                                        "expected_concepts": question_data.get(
                                            "expected_concepts",
                                            [],
                                        ),
                                        "keywords": question_data.get(
                                            "keywords",
                                            [],
                                        ),
                                        "is_active": True,
                                    },
                                )
                            )

                            if question_created:
                                total_questions += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Question bank imported successfully!"
            )
        )

        self.stdout.write(f"New roles: {total_roles}")
        self.stdout.write(f"New skills: {total_skills}")
        self.stdout.write(f"New topics: {total_topics}")
        self.stdout.write(f"New questions: {total_questions}")
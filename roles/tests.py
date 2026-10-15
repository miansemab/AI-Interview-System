
from django.test import TestCase

from roles.models import Role, Skill, Topic


class RoleModelTests(TestCase):
    def test_role_can_be_created(self):
        role = Role.objects.create(
            name="Python Backend Developer",
            category="Software Development",
            environment={"language": "Python"},
        )

        self.assertEqual(role.name, "Python Backend Developer")
        self.assertTrue(role.is_active)
        self.assertEqual(role.environment["language"], "Python")

    def test_skill_belongs_to_role(self):
        role = Role.objects.create(name="Python Backend Developer")
        skill = Skill.objects.create(
            role=role,
            name="Python Fundamentals",
            weight=10,
        )

        self.assertEqual(skill.role, role)
        self.assertEqual(role.skills.count(), 1)

    def test_topic_belongs_to_skill(self):
        role = Role.objects.create(name="Python Backend Developer")
        skill = Skill.objects.create(role=role, name="Python")
        topic = Topic.objects.create(skill=skill, name="Operators")

        self.assertEqual(topic.skill, skill)
        self.assertEqual(skill.topics.count(), 1)

    def test_role_string_representation(self):
        role = Role.objects.create(name="Python Backend Developer")

        self.assertEqual(str(role), "Python Backend Developer")
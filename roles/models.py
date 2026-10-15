from django.db import models


class Role(models.Model):
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    environment = models.JSONField(default=dict)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Skill(models.Model):
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="skills",
    )

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    weight = models.PositiveIntegerField(default=10)

    is_required = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-weight", "name"]

    def __str__(self):
        return f"{self.role.name} - {self.name}"


class Topic(models.Model):
    skill = models.ForeignKey(
        Skill,
        on_delete=models.CASCADE,
        related_name="topics",
    )

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.skill.name} - {self.name}"
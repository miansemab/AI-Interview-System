from django.contrib import admin

from .models import Role, Skill, Topic


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "is_active",
        "created_at",
    )

    list_filter = (
        "is_active",
        "category",
    )

    search_fields = (
        "name",
        "category",
    )


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "role",
        "weight",
        "is_required",
        "is_active",
    )

    list_filter = (
        "role",
        "is_required",
        "is_active",
    )

    search_fields = (
        "name",
        "role__name",
    )


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "skill",
        "is_active",
    )

    list_filter = (
        "skill",
        "is_active",
    )

    search_fields = (
        "name",
        "skill__name",
    )
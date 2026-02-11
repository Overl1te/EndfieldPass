import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update a superuser from DJANGO_SUPERUSER_* environment variables."

    def handle(self, *args, **options):
        username = str(os.getenv("DJANGO_SUPERUSER_USERNAME", "")).strip()
        password = str(os.getenv("DJANGO_SUPERUSER_PASSWORD", "")).strip()
        email = str(os.getenv("DJANGO_SUPERUSER_EMAIL", "admin@endfieldpass.local")).strip() or "admin@endfieldpass.local"

        if not username or not password:
            self.stdout.write(
                self.style.WARNING(
                    "Skipping superuser setup: set DJANGO_SUPERUSER_USERNAME and DJANGO_SUPERUSER_PASSWORD in .env."
                )
            )
            return

        user_model = get_user_model()
        username_field = str(user_model.USERNAME_FIELD or "username")

        defaults = {}
        user_field_names = {field.name for field in user_model._meta.get_fields()}
        if "email" in user_field_names:
            defaults["email"] = email

        lookup = {username_field: username}
        user, created = user_model.objects.get_or_create(**lookup, defaults=defaults)

        if "email" in user_field_names and getattr(user, "email", "") != email:
            user.email = email

        if hasattr(user, "is_staff"):
            user.is_staff = True
        if hasattr(user, "is_superuser"):
            user.is_superuser = True
        if hasattr(user, "is_active"):
            user.is_active = True

        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Superuser created: {username}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser updated: {username}"))


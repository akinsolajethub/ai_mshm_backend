"""
apps/accounts/management/commands/generate_unique_ids.py
────────────────────────────────────────────────────────
Generate unique IDs for existing users who don't have one.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.accounts.id_generator import generate_id_for_user

User = get_user_model()


class Command(BaseCommand):
    help = "Generate unique IDs for existing users who don't have one"

    def handle(self, *args, **options):
        users_without_id = User.objects.filter(unique_id__isnull=True)
        count = users_without_id.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS("All users already have unique IDs."))
            return

        self.stdout.write(f"Found {count} users without unique IDs. Generating...")

        for user in users_without_id:
            generate_id_for_user(user)
            self.stdout.write(f"  Generated {user.unique_id} for {user.email} ({user.role})")

        self.stdout.write(self.style.SUCCESS(f"Successfully generated IDs for {count} users."))

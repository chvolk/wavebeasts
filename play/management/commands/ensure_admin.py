"""Create or update the Django admin login from ADMIN_USERNAME / ADMIN_PASSWORD (run at boot).

Players sign in through Clerk and never get Django passwords, so /admin/ needs its own staff account.
Setting the two env vars on the host creates (or re-keys) a superuser on the next deploy; unsetting
them leaves the existing account alone. ADMIN_EMAIL is optional.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure the superuser named by ADMIN_USERNAME exists with ADMIN_PASSWORD (no-op when unset)."

    def handle(self, *args, **options):
        username = (os.environ.get("ADMIN_USERNAME") or "").strip()
        password = os.environ.get("ADMIN_PASSWORD") or ""
        if not username or not password:
            self.stdout.write("ensure_admin: ADMIN_USERNAME/ADMIN_PASSWORD not set; skipping")
            return
        User = get_user_model()
        user, created = User.objects.get_or_create(username=username, defaults={"email": os.environ.get("ADMIN_EMAIL", "")})
        user.is_staff = user.is_superuser = user.is_active = True
        if not user.check_password(password):
            user.set_password(password)
        user.save()
        self.stdout.write(f"ensure_admin: {'created' if created else 'updated'} superuser {username}")

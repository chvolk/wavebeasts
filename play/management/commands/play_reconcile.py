"""Re-verify Google Play subscriptions that are near expiry, in case a real-time notification was
missed. Run daily (Railway cron): python manage.py play_reconcile"""
from django.core.management.base import BaseCommand

from play import playbilling


class Command(BaseCommand):
    help = "Re-verify Google Play subscriptions near expiry against the Play Developer API."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=200)

    def handle(self, *args, **options):
        if not playbilling.configured():
            self.stdout.write("PLAY_SERVICE_ACCOUNT_JSON not set; nothing to do.")
            return
        checked, changed = playbilling.reconcile(limit=options["limit"])
        self.stdout.write(f"checked {checked} Play subscription(s), {changed} changed")

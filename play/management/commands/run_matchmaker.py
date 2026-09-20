import time

from django.core.management.base import BaseCommand

from play.ladder import run_round


class Command(BaseCommand):
    help = "Resolve async-PvP ladder matches passively (pair up entrants and battle them)."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="run forever on an interval")
        parser.add_argument("--interval", type=int, default=180, help="seconds between rounds when looping")

    def handle(self, *args, **opts):
        if not opts["loop"]:
            self.stdout.write(f"resolved {run_round()} matches")
            return
        iv = max(30, opts["interval"])
        self.stdout.write(f"matchmaker: a round every {iv}s")
        while True:
            try:
                n = run_round()
                if n:
                    self.stdout.write(f"round: {n} matches")
            except Exception as e:  # keep the loop alive
                self.stderr.write(f"round error: {e}")
            time.sleep(iv)

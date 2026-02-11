from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.bootstrap import run_data_bootstrap


class Command(BaseCommand):
    help = "Bootstrap required application data into DB (localization, static characters, weapon catalog)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to use.",
        )
        parser.add_argument(
            "--source",
            default="",
            help="Optional path to localization JSON source file.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run bootstrap even if state hash is up-to-date.",
        )
        parser.add_argument(
            "--allow-in-tests",
            action="store_true",
            help="Allow bootstrap execution when command runs in test process.",
        )

    def handle(self, *args, **options):
        source_raw = str(options.get("source") or "").strip()
        source_path = Path(source_raw) if source_raw else None

        if options.get("allow_in_tests"):
            import os

            os.environ["ENDFIELDPASS_AUTO_BOOTSTRAP_IN_TESTS"] = "1"

        try:
            result = run_data_bootstrap(
                using=str(options.get("database") or "default"),
                force=bool(options.get("force")),
                verbosity=int(options.get("verbosity") or 1),
                source_path=source_path,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        status = str(result.get("status") or "").strip()
        if status in {"done", "up_to_date", "disabled", "skipped_in_tests"}:
            self.stdout.write(self.style.SUCCESS(f"bootstrap_app_data: {result}"))
            return
        if status == "missing_source":
            raise CommandError(f"bootstrap_app_data: {result}")
        self.stdout.write(f"bootstrap_app_data: {result}")

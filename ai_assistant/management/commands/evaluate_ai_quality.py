"""Evaluate reviewed synthetic AI responses against the versioned release gate."""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai_assistant.evaluation import evaluate_assessments, load_dataset


class Command(BaseCommand):
    help = "Score human-reviewed synthetic AI quality assessments."

    def add_arguments(self, parser):
        parser.add_argument("assessments", type=Path)
        parser.add_argument("--dataset", type=Path)
        parser.add_argument("--output", type=Path)

    def handle(self, *args, **options):
        try:
            dataset = (
                load_dataset(options["dataset"])
                if options.get("dataset")
                else load_dataset()
            )
            submission = json.loads(
                options["assessments"].read_text(encoding="utf-8")
            )
            report = evaluate_assessments(dataset, submission)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CommandError(
                f"AI quality evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc
        serialized = json.dumps(report, indent=2, sort_keys=True)
        if options.get("output"):
            options["output"].write_text(serialized + "\n", encoding="utf-8")
            self.stdout.write(str(options["output"]))
        else:
            self.stdout.write(serialized)
        if not report["ready"]:
            raise CommandError("AI quality release thresholds were not met")

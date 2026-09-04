"""Explicitly opt-in to collecting live provider output for synthetic cases."""

import json
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from ai_assistant.evaluation import load_dataset
from ai_assistant.services import get_llm_service


class Command(BaseCommand):
    help = "Call the selected provider with synthetic quality prompts only."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--dataset", type=Path)
        parser.add_argument(
            "--i-understand-provider-costs",
            action="store_true",
            dest="approved",
        )

    def handle(self, *args, **options):
        if not options["approved"]:
            raise CommandError(
                "Live collection requires --i-understand-provider-costs"
            )
        dataset = (
            load_dataset(options["dataset"])
            if options.get("dataset")
            else load_dataset()
        )
        service = get_llm_service(use_case="chat")
        readiness = service.readiness()
        if not readiness.get("available"):
            raise CommandError("Selected AI provider/model is not available")
        assessments = []
        execution_modes = {
            "provider": 0,
            "policy": 0,
            "controlled_guidance": 0,
        }
        for case in dataset["cases"]:
            result = service.chat(
                case["prompt"],
                language=case["language"],
                max_tokens=256,
            )
            if not result.get("success"):
                raise CommandError(
                    f"Provider failed on synthetic case {case['id']}: "
                    f"{result.get('code', 'AI_PROVIDER_ERROR')}"
                )
            if result.get("policy_intercepted"):
                execution_mode = "policy"
            elif result.get("controlled_response"):
                execution_mode = "controlled_guidance"
            else:
                execution_mode = "provider"
            execution_modes[execution_mode] += 1
            assessments.append({
                "case_id": case["id"],
                "response": result.get("response", ""),
                "scores": {},
                "critical_failure": False,
                "execution_mode": execution_mode,
            })
        payload = {
            "dataset_version": dataset["dataset_version"],
            "dataset_sha256": dataset["dataset_sha256"],
            "provider": readiness["provider"],
            "model": readiness["model"],
            "reviewer": "REQUIRED_BEFORE_EVALUATION",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "execution_mode_counts": execution_modes,
            "assessments": assessments,
        }
        options["output"].write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.stdout.write(str(options["output"]))

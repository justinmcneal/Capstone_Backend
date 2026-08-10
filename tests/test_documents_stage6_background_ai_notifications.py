"""Stage 6 durable analysis, artifact safety, and notification coverage."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bson import ObjectId
from PIL import Image

from documents.models import Document, DocumentNotificationDelivery
from documents.services.analysis import (
    process_document_analysis,
    queue_document_analysis,
    reconcile_due_document_analyses,
)
from documents.services.analyzer import DocumentAnalyzer
from documents.services.notification import (
    deliver_reviewer_notification,
    reconcile_reviewer_notifications,
)
from documents.services.preprocessing import ResizeWithPadding
from documents.tasks import analyze_document_task
from scripts.approve_document_model import approval_check
from scripts.check_training_data import EXPECTED_CLASSES, validate_dataset
from scripts.evaluate_document_model import evaluate_records


def _document(**kwargs):
    return Document(
        customer_id=kwargs.pop("customer_id", str(ObjectId())),
        document_type=kwargs.pop("document_type", "valid_id"),
        original_filename="id.jpg",
        file_path=f"documents/{ObjectId()}/id.jpg",
        file_size=1024,
        mime_type=kwargs.pop("mime_type", "image/jpeg"),
        **kwargs,
    ).save()


def test_analysis_enqueue_failure_remains_durably_pending(monkeypatch, settings):
    document = _document()
    monkeypatch.setattr(
        "documents.tasks.analyze_document_task.delay",
        lambda document_id: (_ for _ in ()).throw(RuntimeError("broker down")),
    )

    assert queue_document_analysis(document) is False

    stored = Document.find_by_id(document.id)
    assert stored.ai_analysis_status == "pending"
    assert stored.ai_analysis_next_attempt_at is not None


def test_analysis_task_rechecks_consent_before_reading_document(monkeypatch):
    document = _document()
    assert document.schedule_ai_analysis() is True
    monkeypatch.setattr(
        "documents.services.analysis.ConsentService.check_ai_consent",
        lambda customer_id: False,
    )
    monkeypatch.setattr(
        "documents.storage.get_storage_backend",
        lambda: (_ for _ in ()).throw(AssertionError("storage must not be read")),
    )

    assert analyze_document_task.run(document.id) == "skipped_no_consent"
    stored = Document.find_by_id(document.id)
    assert stored.ai_analysis_status == "skipped_no_consent"
    assert stored.ai_analysis == {}


def test_analysis_persists_trace_and_cannot_override_human_review(monkeypatch):
    document = _document(status="approved", verified=True)
    assert document.schedule_ai_analysis() is True
    monkeypatch.setattr(
        "documents.services.analysis.ConsentService.check_ai_consent",
        lambda customer_id: True,
    )
    monkeypatch.setattr(
        "documents.storage.get_storage_backend",
        lambda: SimpleNamespace(get_file_bytes=lambda path: b"image"),
    )
    monkeypatch.setattr(
        "documents.services.analyze_document",
        lambda contents, expected_type: {
            "is_valid": False,
            "quality_score": 0.2,
            "analysis_status": "completed",
            "model_version": "classifier-v7",
            "preprocessing_version": "preprocess-v2",
            "threshold_policy_version": "threshold-v3",
            "manual_review_required": True,
        },
    )

    assert process_document_analysis(document.id) == "completed"
    stored = Document.find_by_id(document.id)
    assert stored.ai_analysis_status == "completed"
    assert stored.ai_analysis["model_version"] == "classifier-v7"
    assert stored.ai_analyzed_at is not None
    assert stored.status == "approved"
    assert stored.verified is True


def test_analysis_failure_uses_safe_codes_and_stops_after_bound(monkeypatch, settings):
    settings.DOCUMENT_AI_MAX_ATTEMPTS = 2
    settings.DOCUMENT_AI_RETRY_BACKOFF_SECONDS = 1
    document = _document()
    assert document.schedule_ai_analysis() is True
    monkeypatch.setattr(
        "documents.services.analysis.ConsentService.check_ai_consent",
        lambda customer_id: True,
    )
    monkeypatch.setattr(
        "documents.storage.get_storage_backend",
        lambda: SimpleNamespace(
            get_file_bytes=lambda path: (_ for _ in ()).throw(
                RuntimeError("secret storage detail")
            )
        ),
    )

    assert process_document_analysis(document.id) == "retry_wait"
    settings.MONGODB[Document.collection_name].update_one(
        {"_id": ObjectId(document.id)},
        {"$set": {"ai_analysis_next_attempt_at": datetime.now(timezone.utc)}},
    )
    assert process_document_analysis(document.id) == "failed"

    stored = Document.find_by_id(document.id)
    assert stored.ai_analysis_status == "failed"
    assert stored.ai_analysis_attempts == 2
    assert stored.ai_analysis_last_error_code == "analysis_execution_failed"
    assert "secret" not in str(stored.to_dict())


def test_reconciler_republishes_only_due_analysis(monkeypatch, settings):
    due = _document()
    future = _document()
    due.schedule_ai_analysis()
    future.schedule_ai_analysis()
    settings.MONGODB[Document.collection_name].update_one(
        {"_id": ObjectId(future.id)},
        {
            "$set": {
                "ai_analysis_next_attempt_at": datetime.now(timezone.utc)
                + timedelta(hours=1)
            }
        },
    )
    queued = []
    monkeypatch.setattr("documents.tasks.analyze_document_task.delay", queued.append)

    assert reconcile_due_document_analyses() == 1
    assert queued == [due.id]


def test_abandoned_analysis_lease_can_be_reclaimed(settings):
    document = _document()
    document.schedule_ai_analysis()
    settings.MONGODB[Document.collection_name].update_one(
        {"_id": ObjectId(document.id)},
        {
            "$set": {
                "ai_analysis_status": "processing",
                "ai_analysis_started_at": datetime.now(timezone.utc)
                - timedelta(minutes=10),
            }
        },
    )

    assert document.id in Document.find_due_ai_analyses()

    claimed = Document.claim_ai_analysis(document.id, lease_seconds=60)

    assert claimed is not None
    assert claimed.ai_analysis_status == "processing"
    assert claimed.ai_analysis_attempts == 1


def test_notification_outbox_is_idempotent_and_retries_failure(monkeypatch, settings):
    DocumentNotificationDelivery.create_indexes()
    document = _document()
    recipient = {
        "email": "reviewer@example.test",
        "name": "Review User",
        "user_id": str(ObjectId()),
        "user_type": "loan_officer",
    }
    delivery = DocumentNotificationDelivery.ensure(
        document=document,
        recipient=recipient,
        customer_name="Customer Name",
    )
    calls = []

    class Sender:
        def send_document_pending_review(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("smtp detail")
            return True

    monkeypatch.setattr(
        "documents.services.notification.get_email_sender", lambda: Sender()
    )

    assert deliver_reviewer_notification(delivery.id) == "retry_wait"
    raw = settings.MONGODB[delivery.collection_name].find_one(
        {"_id": ObjectId(delivery.id)}
    )
    assert raw["status"] == "retry_wait"
    assert raw["last_error_code"] == "delivery_failed"
    assert "smtp detail" not in str(raw)

    settings.MONGODB[delivery.collection_name].update_one(
        {"_id": ObjectId(delivery.id)},
        {"$set": {"next_attempt_at": datetime.now(timezone.utc)}},
    )
    assert reconcile_reviewer_notifications()["delivered"] == 1
    assert deliver_reviewer_notification(delivery.id) == "not_due"

    same = DocumentNotificationDelivery.ensure(
        document=document,
        recipient=recipient,
        customer_name="Customer Name",
    )
    assert same.id == delivery.id
    assert len(calls) == 2


def test_in_app_notification_is_idempotent_across_email_retries(monkeypatch, settings):
    from notifications.models import Notification
    from notifications.services.notification_creator import (
        create_and_broadcast_notification,
    )

    Notification.create_indexes()
    broadcasts = []
    monkeypatch.setattr(
        "notifications.services.notification_creator.broadcast_notification_to_user",
        lambda *args: broadcasts.append(args),
    )
    monkeypatch.setattr(
        "notifications.services.notification_creator._send_push_notification",
        lambda *args: None,
    )
    kwargs = {
        "user_id": "reviewer-1",
        "user_type": "loan_officer",
        "notification_type": "document_pending_review",
        "subject": "Review",
        "message": "Review a document",
        "related_type": "document",
        "related_id": "document-1",
        "idempotency_key": "delivery-1",
    }

    first = create_and_broadcast_notification(**kwargs)
    second = create_and_broadcast_notification(**kwargs)

    assert first.id == second.id
    assert settings.MONGODB[Notification.collection_name].count_documents({}) == 1
    assert len(broadcasts) == 1


def test_analyzer_failure_is_fail_closed_without_exception_text(monkeypatch):
    analyzer = DocumentAnalyzer.__new__(DocumentAnalyzer)
    analyzer.model = None
    analyzer.model_loaded = False
    analyzer.class_names = None
    analyzer.model_metadata = {"model_version": "test-v1"}
    analyzer.model_error_code = "artifact_missing"
    monkeypatch.setattr(
        "documents.services.analyzer.Image.open",
        lambda value: (_ for _ in ()).throw(RuntimeError("private decoder detail")),
    )

    result = analyzer.analyze(b"invalid", expected_type="valid_id")

    assert result["is_valid"] is False
    assert result["analysis_status"] == "failed"
    assert result["manual_review_required"] is True
    assert "error" not in result
    assert "private decoder detail" not in str(result)


def test_approved_artifact_loader_never_requests_pretrained_weights(
    monkeypatch, tmp_path
):
    import torch

    from documents.services import analyzer as analyzer_module
    from documents.services import cnn_model

    fake_service_file = tmp_path / "documents" / "services" / "analyzer.py"
    model_dir = tmp_path / "documents" / "ml" / "models"
    model_dir.mkdir(parents=True)
    model_path = model_dir / "document_classifier.pth"
    model_path.write_bytes(b"approved-state")
    config = {
        "classes": ["valid_id"],
        "approval_status": "approved",
        "artifact_sha256": hashlib.sha256(b"approved-state").hexdigest(),
        "model_version": "approved-v1",
        "dataset_manifest_sha256": "dataset-hash",
        "evaluation_report_sha256": "evaluation-hash",
        "approved_by": "test-approver",
        "approved_at": "2026-08-10T00:00:00+00:00",
        "rollback_target": "approved-v0",
        "preprocessing_version": "document-photo-letterbox-v2",
        "threshold_policy_version": "document-type-thresholds-v1",
    }
    (model_dir / "model_config.json").write_text(json.dumps(config), encoding="utf-8")
    constructor_calls = []

    class FakeClassifier:
        def __init__(self, *, num_classes, pretrained):
            constructor_calls.append((num_classes, pretrained))

        def load_state_dict(self, state):
            assert state == {"state": "ok"}

        def eval(self):
            return self

    monkeypatch.setattr(analyzer_module, "Path", lambda value: fake_service_file)
    monkeypatch.setattr(cnn_model, "DocumentClassifier", FakeClassifier)
    monkeypatch.setattr(torch, "load", lambda *args, **kwargs: {"state": "ok"})

    analyzer = DocumentAnalyzer()

    assert analyzer.model_loaded is True
    assert constructor_calls == [(1, False)]
    assert analyzer.health()["model_version"] == "approved-v1"


def test_low_confidence_classification_becomes_unknown_instead_of_forced(
    monkeypatch,
):
    import torch

    analyzer = DocumentAnalyzer.__new__(DocumentAnalyzer)
    analyzer.model_loaded = True
    analyzer.class_names = ["valid_id", "business_permit"]
    analyzer.model = lambda tensor: torch.tensor([[0.1, 0.2]])
    monkeypatch.setattr(
        "documents.services.analyzer.build_inference_transform",
        lambda: lambda image: torch.zeros((3, 224, 224)),
    )

    result = analyzer._classify(Image.new("RGB", (320, 200)))

    assert result["raw_predicted_type"] == "business_permit"
    assert result["predicted_type"] == "unknown"
    assert result["unknown_or_ood"] is True


def test_preprocessing_letterboxes_without_aspect_distortion():
    transformed = ResizeWithPadding(224)(Image.new("RGB", (400, 100), "black"))

    assert transformed.size == (224, 224)
    assert transformed.getpixel((112, 112)) == (0, 0, 0)
    assert transformed.getpixel((112, 0)) == (255, 255, 255)


def test_evaluation_and_approval_tools_bind_artifact_dataset_and_policy(tmp_path):
    artifact = tmp_path / "model.pth"
    artifact.write_bytes(b"candidate")
    artifact_hash = hashlib.sha256(b"candidate").hexdigest()
    records = []
    for class_name in (*EXPECTED_CLASSES, "unknown"):
        records.append(
            {
                "true_type": class_name,
                "predicted_type": class_name,
                "confidence": 0.99,
                "subject_id": f"subject-{class_name}",
                "subgroup": "synthetic",
                "latency_ms": 20,
            }
        )
    payload = {
        "artifact_sha256": artifact_hash,
        "dataset_manifest_sha256": "dataset-hash",
        "preprocessing_version": "preprocess-v2",
        "threshold_policy_version": "threshold-v1",
        "records": records,
    }
    report = evaluate_records(payload, minimum_per_class=1)
    config = {
        "artifact_sha256": artifact_hash,
        "dataset_manifest_sha256": "dataset-hash",
        "preprocessing_version": "preprocess-v2",
        "threshold_policy_version": "threshold-v1",
        "rollback_target": "approved-v0",
    }

    assert report["passes_gates"] is True
    assert report["macro_f1"] == 1.0
    assert report["ood_recall"] == 1.0
    assert approval_check(config, report, artifact) == []

    report["dataset_manifest_sha256"] = "different-data"
    assert "evaluation_dataset_manifest_sha256_mismatch" in approval_check(
        config, report, artifact
    )


def test_document_indexes_include_ai_reconciliation(settings):
    Document.create_indexes()
    indexes = settings.MONGODB[Document.collection_name].index_information()
    assert "document_ai_analysis_reconciliation" in indexes


def test_dataset_checker_requires_provenance_grouped_splits_and_unique_files(
    tmp_path,
):
    entries = []
    for class_index, class_name in enumerate(EXPECTED_CLASSES):
        class_dir = tmp_path / class_name
        class_dir.mkdir()
        for sample_index in range(2):
            path = class_dir / f"sample-{sample_index}.png"
            Image.new(
                "RGB",
                (224, 224),
                color=(class_index * 20, sample_index * 40, class_index + sample_index),
            ).save(path)
            entries.append(
                {
                    "path": path.relative_to(tmp_path).as_posix(),
                    "source": "synthetic-test",
                    "license_or_consent_basis": "generated",
                    "anonymized": True,
                    "subject_id": f"subject-{class_index}-{sample_index}",
                    "split": "train" if sample_index == 0 else "holdout",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    manifest = tmp_path / "dataset_manifest.json"
    manifest.write_text(json.dumps({"entries": entries}), encoding="utf-8")

    report = validate_dataset(tmp_path, manifest, min_samples=2)
    assert report["ready"] is True

    entries[1]["subject_id"] = entries[0]["subject_id"]
    entries[1]["anonymized"] = False
    manifest.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    unsafe = validate_dataset(tmp_path, manifest, min_samples=2)
    assert unsafe["ready"] is False
    assert any(
        issue.startswith("anonymization_unapproved:") for issue in unsafe["issues"]
    )
    assert any(issue.startswith("subject_cross_split:") for issue in unsafe["issues"])

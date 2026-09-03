"""
Document Analysis Service - Quality Check & CNN Classification

Currently implements:
- Quality checks (blur detection, size validation)
- Image preprocessing

Future (after training data collected):
- MobileNetV2 document classification
- Document type prediction
"""

import hashlib
import importlib.util
import io
import json
import logging
from pathlib import Path

from django.conf import settings
from PIL import Image

from documents.services.preprocessing import (
    PREPROCESSING_VERSION,
    build_inference_transform,
)

logger = logging.getLogger("documents")

# Configuration
MIN_IMAGE_SIZE = (200, 200)  # Minimum dimensions
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BLUR_THRESHOLD = 100  # Laplacian variance threshold
TYPE_CONFIDENCE_THRESHOLD = settings.DOCUMENT_TYPE_CONFIDENCE_THRESHOLD
ENFORCE_TYPE_MATCH = settings.DOCUMENT_ENFORCE_TYPE_MATCH
REQUIRE_CNN_FOR_TYPE_VALIDATION = settings.DOCUMENT_REQUIRE_CNN_FOR_TYPE_VALIDATION
REQUIRE_BLUR_CHECK = settings.DOCUMENT_AI_REQUIRE_BLUR_CHECK
THRESHOLD_POLICY_VERSION = "document-type-thresholds-v1"


class DocumentAnalyzer:
    """
    Analyzes uploaded documents for quality and classification.

    Current mode: Quality-check only
    Future mode: CNN classification with MobileNetV2
    """

    def __init__(self):
        self.model = None
        self.model_loaded = False
        self.class_names = None  # Loaded from model_config.json
        self.model_metadata = {}
        self.model_error_code = "artifact_missing"
        self.model_runtime_status = "unavailable"
        self._try_load_model()

    def _try_load_model(self):
        """Try to load trained CNN model if available"""
        model_dir = Path(__file__).parent.parent / "ml" / "models"
        model_path = model_dir / "document_classifier.pth"
        config_path = model_dir / "model_config.json"

        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as config_file:
                    self.model_metadata = json.load(config_file)
            except (OSError, ValueError):
                logger.exception("Document model registry could not be read")
                self.model_error_code = "registry_invalid"
                return

        if not model_path.exists():
            logger.info("No trained CNN model found - using quality-check mode")
            return

        try:
            import torch

            from .cnn_model import DOCUMENT_CLASSES, DocumentClassifier

            expected_hash = self.model_metadata.get("artifact_sha256")
            approval_status = self.model_metadata.get("approval_status")
            approval_required = bool(settings.DOCUMENT_AI_REQUIRE_APPROVED_MODEL)
            allow_unapproved_dev = bool(settings.DEBUG) and not approval_required
            if not expected_hash:
                self.model_error_code = "registry_invalid"
                logger.error("CNN artifact registry is missing its artifact hash")
                return
            if approval_status != "approved" and not allow_unapproved_dev:
                self.model_error_code = "artifact_not_approved"
                logger.warning(
                    "CNN artifact is present but not approved in its registry"
                )
                return
            if approval_status == "approved":
                required_registry_fields = (
                    "model_version",
                    "dataset_manifest_sha256",
                    "evaluation_report_sha256",
                    "approved_by",
                    "approved_at",
                    "rollback_target",
                )
                if any(
                    not self.model_metadata.get(field)
                    for field in required_registry_fields
                ):
                    self.model_error_code = "registry_approval_incomplete"
                    logger.error("Approved CNN registry entry is incomplete")
                    return
            if (
                self.model_metadata.get("preprocessing_version")
                != PREPROCESSING_VERSION
                or self.model_metadata.get("threshold_policy_version")
                != THRESHOLD_POLICY_VERSION
            ):
                self.model_error_code = "registry_policy_mismatch"
                logger.error("CNN registry policy version does not match runtime")
                return
            actual_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                self.model_error_code = "artifact_hash_mismatch"
                logger.error("CNN artifact hash does not match its registry entry")
                return

            self.class_names = self.model_metadata.get("classes", DOCUMENT_CLASSES)
            if not self.class_names:
                self.model_error_code = "class_mapping_missing"
                return

            # Inference must never attempt to download pretrained weights. The
            # complete hash-verified state dict is loaded immediately afterwards.
            self.model = DocumentClassifier(
                num_classes=len(self.class_names), pretrained=False
            )
            self.model.load_state_dict(
                torch.load(model_path, map_location="cpu", weights_only=True)
            )
            self.model.eval()
            self.model_loaded = True
            self.model_error_code = ""
            self.model_runtime_status = (
                "available"
                if approval_status == "approved"
                else "available_unapproved_dev"
            )
            logger.info(
                "%s CNN model loaded: %s",
                "Approved" if approval_status == "approved" else "Unapproved development",
                self.model_metadata.get("model_version", "unversioned"),
            )
        except Exception:
            logger.exception("Could not load CNN model")
            self.model_error_code = "artifact_load_failed"
            self.model_loaded = False

    def analyze(self, file_path_or_bytes, expected_type=None):
        """
        Analyze a document image.

        Args:
            file_path_or_bytes: Path to image or bytes
            expected_type: Expected document type (optional)

        Returns:
            dict with analysis results
        """
        try:
            # Load image
            if isinstance(file_path_or_bytes, (str, Path)):
                image = Image.open(file_path_or_bytes)
            else:
                image = Image.open(io.BytesIO(file_path_or_bytes))

            # Convert to RGB if needed
            if image.mode != "RGB":
                image = image.convert("RGB")

            # Run quality checks
            quality_result = self._check_quality(image)

            # Run CNN classification if model available
            if self.model_loaded:
                classification = self._classify(image)
            else:
                classification = {
                    "predicted_type": "unknown",
                    "type_confidence": None,
                    "model_available": False,
                }

            type_validation = self._validate_type(expected_type, classification)
            combined_issues = quality_result["issues"] + type_validation["issues"]

            # Combine results
            return {
                "is_valid": quality_result["is_valid"] and type_validation["is_valid"],
                "quality_score": quality_result["quality_score"],
                "quality_issues": combined_issues,
                "expected_type": expected_type,
                "predicted_type": classification["predicted_type"],
                "raw_predicted_type": classification.get("raw_predicted_type"),
                "unknown_or_ood": classification.get("unknown_or_ood", True),
                "type_confidence": classification.get("type_confidence"),
                "type_matches_expected": type_validation["type_matches_expected"],
                "type_validation_passed": type_validation["is_valid"],
                "type_confidence_threshold": TYPE_CONFIDENCE_THRESHOLD,
                "model_available": self.model_loaded,
                "model_status": getattr(self, "model_runtime_status", "available")
                if self.model_loaded
                else self.model_error_code,
                "model_version": self.model_metadata.get("model_version"),
                "preprocessing_version": PREPROCESSING_VERSION,
                "threshold_policy_version": THRESHOLD_POLICY_VERSION,
                "analysis_mode": "cnn" if self.model_loaded else "quality_check",
                "analysis_status": "completed",
                "manual_review_required": True,
            }

        except Exception:
            logger.exception("Document analysis failed")
            return {
                "is_valid": False,
                "quality_score": 0,
                "quality_issues": ["Could not analyze image"],
                "analysis_mode": "failed",
                "analysis_status": "failed",
                "model_available": self.model_loaded,
                "model_status": getattr(self, "model_runtime_status", "available")
                if self.model_loaded
                else self.model_error_code,
                "model_version": self.model_metadata.get("model_version"),
                "preprocessing_version": PREPROCESSING_VERSION,
                "threshold_policy_version": THRESHOLD_POLICY_VERSION,
                "manual_review_required": True,
            }

    def _check_quality(self, image):
        """
        Check image quality.

        Checks:
        - Image size (minimum dimensions)
        - Blur detection (using Laplacian variance)
        - Brightness check
        """
        issues = []
        score = 100

        # Check dimensions
        width, height = image.size
        if width < MIN_IMAGE_SIZE[0] or height < MIN_IMAGE_SIZE[1]:
            issues.append(
                f"Image too small ({width}x{height}). Minimum: {MIN_IMAGE_SIZE[0]}x{MIN_IMAGE_SIZE[1]}"
            )
            score -= 30

        # Check aspect ratio (too extreme = likely cropped badly)
        aspect = max(width, height) / min(width, height)
        if aspect > 5:
            issues.append("Unusual aspect ratio - image may be cropped incorrectly")
            score -= 15

        # Check blur using Laplacian variance (requires numpy/cv2)
        try:
            blur_score = self._check_blur(image)
        except ImportError:
            if REQUIRE_BLUR_CHECK:
                raise
        else:
            if blur_score < BLUR_THRESHOLD:
                issues.append(f"Image appears blurry (score: {blur_score:.0f})")
                score -= 25

        # Check brightness
        brightness = self._check_brightness(image)
        if brightness < 40:
            issues.append("Image too dark")
            score -= 20
        elif brightness > 240:
            issues.append("Image too bright/overexposed")
            score -= 20

        score = max(0, min(100, score))

        return {
            "is_valid": len(issues) == 0 or score >= 50,
            "quality_score": score / 100,
            "issues": issues,
        }

    def _check_blur(self, image):
        """Check blur using Laplacian variance"""
        import cv2
        import numpy as np

        img_array = np.array(image)
        gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        return laplacian.var()

    def _check_brightness(self, image):
        """Check average brightness"""
        try:
            import numpy as np

            img_array = np.array(image)
            return np.mean(img_array)
        except ImportError:
            # Fallback without numpy
            pixels = list(image.getdata())
            avg = sum(sum(p[:3]) / 3 for p in pixels) / len(pixels)
            return avg

    def _classify(self, image):
        """Classify document type using CNN (if model loaded)"""
        if not self.model_loaded:
            return {"predicted_type": "unknown", "type_confidence": None}

        try:
            import torch

            img_tensor = build_inference_transform()(image).unsqueeze(0)

            # Predict
            with torch.no_grad():
                outputs = self.model(img_tensor)
                probabilities = torch.softmax(outputs, dim=1)
                confidence, predicted = torch.max(probabilities, 1)

            # Map index → class name using config loaded at init
            predicted_idx = predicted.item()
            if self.class_names and 0 <= predicted_idx < len(self.class_names):
                predicted_name = self.class_names[predicted_idx]
            else:
                predicted_name = "unknown"

            confidence_value = confidence.item()
            raw_predicted_type = predicted_name
            if confidence_value < TYPE_CONFIDENCE_THRESHOLD:
                predicted_name = "unknown"

            return {
                "predicted_type": predicted_name,
                "raw_predicted_type": raw_predicted_type,
                "type_confidence": confidence_value,
                "unknown_or_ood": predicted_name == "unknown",
            }

        except Exception:
            logger.exception("Document classification failed")
            raise

    def health(self):
        """Return non-sensitive artifact readiness for startup/health checks."""
        blur_available = all(
            importlib.util.find_spec(name) is not None for name in ("cv2", "numpy")
        )
        model_required = bool(settings.DOCUMENT_AI_REQUIRE_APPROVED_MODEL)
        ready = (not model_required or self.model_loaded) and (
            not REQUIRE_BLUR_CHECK or blur_available
        )
        return {
            "ready": ready,
            "model_available": self.model_loaded,
            "status": (
                "dependency_missing"
                if REQUIRE_BLUR_CHECK and not blur_available
                else getattr(self, "model_runtime_status", "available")
                if self.model_loaded
                else self.model_error_code
            ),
            "model_version": self.model_metadata.get("model_version"),
            "approval_status": self.model_metadata.get("approval_status", "missing"),
            "preprocessing_version": PREPROCESSING_VERSION,
            "threshold_policy_version": THRESHOLD_POLICY_VERSION,
            "blur_check_required": REQUIRE_BLUR_CHECK,
            "blur_check_available": blur_available,
        }

    def _validate_type(self, expected_type, classification):
        """Validate predicted type against expected upload type."""
        issues = []

        # No expected type means nothing to validate.
        if not expected_type:
            return {
                "is_valid": True,
                "issues": issues,
                "type_matches_expected": None,
            }

        predicted_type = classification.get("predicted_type")
        type_confidence = classification.get("type_confidence")

        # If CNN is unavailable, do not treat type as verified.
        if not self.model_loaded:
            if REQUIRE_CNN_FOR_TYPE_VALIDATION:
                issues.append(
                    "CNN model unavailable; document type could not be validated"
                )
                return {
                    "is_valid": False,
                    "issues": issues,
                    "type_matches_expected": None,
                }
            return {
                "is_valid": True,
                "issues": issues,
                "type_matches_expected": None,
            }

        if expected_type == "other":
            issues.append("Other document types require manual review")
            return {
                "is_valid": False,
                "issues": issues,
                "type_matches_expected": None,
            }

        type_matches_expected = predicted_type == expected_type

        if ENFORCE_TYPE_MATCH and not type_matches_expected:
            issues.append(
                f"Document type mismatch (expected: {expected_type}, predicted: {predicted_type})"
            )

        if type_confidence is None:
            issues.append("CNN type confidence unavailable")
        elif type_confidence < TYPE_CONFIDENCE_THRESHOLD:
            issues.append(
                f"Low type confidence ({type_confidence:.2f} < {TYPE_CONFIDENCE_THRESHOLD:.2f})"
            )

        is_valid = not issues
        return {
            "is_valid": is_valid,
            "issues": issues,
            "type_matches_expected": type_matches_expected,
        }


# Singleton instance
_analyzer = None


def get_analyzer():
    """Get document analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = DocumentAnalyzer()
    return _analyzer


def analyze_document(file_path_or_bytes, expected_type=None):
    """Convenience function to analyze a document"""
    return get_analyzer().analyze(file_path_or_bytes, expected_type)


def get_document_model_health():
    """Return the singleton analyzer's artifact health without file contents."""
    return get_analyzer().health()

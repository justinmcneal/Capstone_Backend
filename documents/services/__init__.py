"""Document services package."""

from .analyzer import DocumentAnalyzer, analyze_document, get_analyzer

__all__ = [
    "DocumentAnalyzer",
    "get_analyzer",
    "analyze_document",
    "DocumentClassifier",
    "DOCUMENT_CLASSES",
]


def __getattr__(name):
    if name in {"DocumentClassifier", "DOCUMENT_CLASSES"}:
        from .cnn_model import DOCUMENT_CLASSES, DocumentClassifier

        return {
            "DocumentClassifier": DocumentClassifier,
            "DOCUMENT_CLASSES": DOCUMENT_CLASSES,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

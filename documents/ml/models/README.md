# Trained Models

This folder stores trained PyTorch models for document analysis.

## Files

After training, you'll have:
- `document_classifier.pth` - Main classification model
- `model_config.json` - Model configuration and class labels

## Current Status

No approved artifact is present. Runtime uses quality-check-only mode and reports
`artifact_missing` through the document-AI health details. `model_config.json`
is a registry-shaped development record with `approval_status: not_approved`;
its historical validation accuracy is not production approval.

Inference will load a `.pth` file only when its SHA-256 matches an independently
approved registry entry. It constructs the architecture with
`pretrained=False`, so service startup never downloads weights.
Low-confidence output is represented as `unknown`, and the shared
`document-photo-letterbox-v2` preprocessing preserves aspect ratio.

To train a model, collect training data and run:
```bash
python manage.py train_document_classifier
```

Training requires a passing `training_data/dataset_manifest.json` and produces
a hashed but deliberately `not_approved` artifact entry. See
`docs/documents/DOCUMENTS_PRODUCTION_READINESS_REVIEW.md` for independent
evaluation, approval,
deployment, and rollback requirements.

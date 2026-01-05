# Trained Models

This folder stores trained PyTorch models for document analysis.

## Files

After training, you'll have:
- `document_classifier.pth` - Main classification model
- `model_config.json` - Model configuration and class labels

## Current Status

No trained model yet. Using quality-check-only mode.

To train a model, collect training data and run:
```bash
python manage.py train_document_classifier
```

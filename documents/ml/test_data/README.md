# Document Analysis ML - Holdout Test Data

This folder contains the **holdout test set** for CNN evaluation.

## Purpose

- Images here are **never used for training**.
- Keep about **20% per class** here.
- Use this folder only for final evaluation after training.

## Folder Structure

```
test_data/
├── valid_id/
├── selfie_with_id/
├── business_permit/
├── proof_of_address/
├── business_photo/
├── income_proof/
└── invalid/
```

## Workflow

1. Put ~80% per class in `documents/ml/training_data/`.
2. Put ~20% per class in `documents/ml/test_data/`.
3. Train model:

```bash
python manage.py train_document_classifier
```

4. Evaluate on holdout set:

```bash
python scripts/test_cnn_model.py documents/ml/test_data --confusion
```

## Security Note

Do not commit real personal documents.

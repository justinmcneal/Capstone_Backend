# Document Analysis (CNN) Guide

## Overview

AI-powered document analysis for uploaded documents.

**Current Mode:** Quality-check only (no trained model yet)
**Future Mode:** CNN classification with MobileNetV2

---

## Features

### Quality Check (Active Now)
- Blur detection (Laplacian variance)
- Brightness check (too dark/bright)
- Size validation (minimum dimensions)
- Auto-flags low quality for review

### CNN Classification (After Training)
- Document type prediction
- Confidence scoring (0-1)
- Invalid document detection

---

## Training Data

### Where to Get It

1. **Kaggle:** https://kaggle.com (search "ID document dataset")
2. **Roboflow:** https://universe.roboflow.com
3. **MIDV-500:** https://github.com/fcakyon/midv500

### Where to Put It

```
documents/ml/training_data/
├── valid_id/           # 50-100 images
├── selfie_with_id/     # 30-50 images
├── business_permit/    # 30-50 images
├── proof_of_address/   # 30-50 images
├── business_photo/     # 30-50 images
├── income_proof/       # 30-50 images
└── invalid/            # 50-100 random images
```

---

## Training the Model

### Prerequisites

```bash
pip install torch torchvision pillow opencv-python
```

### Run Training

```bash
python manage.py train_document_classifier
```

### Options

```bash
python manage.py train_document_classifier --epochs 20
python manage.py train_document_classifier --batch-size 16
python manage.py train_document_classifier --fine-tune  # Full model training
```

### Output

After training:
- `documents/ml/models/document_classifier.pth` - Trained model
- `documents/ml/models/model_config.json` - Configuration

---

## API Response (After Upload)

```json
{
    "status": "success",
    "data": {
        "id": "...",
        "document_type": "valid_id",
        "status": "pending",
        "ai_analysis": {
            "quality_score": 0.85,
            "is_valid": true,
            "quality_issues": [],
            "analysis_mode": "quality_check"
        }
    }
}
```

---

## Quality Issues Detected

| Issue | Description |
|-------|-------------|
| `Image too small` | Below 200x200 pixels |
| `Image appears blurry` | Low sharpness score |
| `Image too dark` | Brightness < 40 |
| `Image too bright` | Brightness > 240 |
| `Unusual aspect ratio` | May be cropped incorrectly |

# Documents and CNN Guide

Merged documentation for document upload testing and CNN training/analysis guides.

## Wave

- Wave: 6
- Status: Done

## Navigation

1. [Document Upload API Testing Guide](#section-1-documents_testing_guidemd)
2. [CNN Document Classifier - Final Guide](#section-2-cnn_final_guidemd)
3. [Document Analysis (CNN) Guide](#section-3-cnn_document_analysismd)
4. [CNN Training Quick Start Guide](#section-4-cnn_quick_startmd)
5. [CNN Document Classifier - Complete Training Guide](#section-5-cnn_training_guidemd)
6. [CNN Model Improvements Playbook](#section-6-cnn_model_improvementsmd)

## Source Files

1. `DOCUMENTS_TESTING_GUIDE.md`
2. `CNN_FINAL_GUIDE.md`
3. `CNN_DOCUMENT_ANALYSIS.md`
4. `CNN_QUICK_START.md`
5. `CNN_TRAINING_GUIDE.md`
6. `CNN_MODEL_IMPROVEMENTS.md`

---

## Section 1: DOCUMENTS_TESTING_GUIDE.md

# Document Upload API Testing Guide

Complete guide to test all document upload endpoints.

---

## Setup

**Base URL:** `http://localhost:8000/api/documents`

**Headers (all requests require authentication):**
```
Authorization: Bearer <customer_access_token>
Content-Type: application/json (for non-upload requests)
Content-Type: multipart/form-data (for uploads)
```

---

## Document Types

| Type | Description | Required |
|------|-------------|----------|
| `valid_id` | Government-issued ID | Yes (for loan) |
| `selfie_with_id` | Selfie holding ID | No |
| `proof_of_address` | Utility bill, barangay cert | No |
| `business_permit` | DTI/SEC/Mayor's permit | No |
| `business_photo` | Photo of business | No |
| `income_proof` | Bank statement (Optional for informal economy) | No |
| `other` | Other documents | No |

---

## Customer Endpoints

### 1. Get Document Types

```
GET /api/documents/types/
```

**Response:**
```json
{
    "status": "success",
    "data": {
        "document_types": [
            {"value": "valid_id", "label": "Valid Government ID", "required": true},
            {"value": "selfie_with_id", "label": "Selfie with ID", "required": false},
            ...
        ]
    }
}
```

---

### 2. Upload Document

```
POST /api/documents/upload/
Content-Type: multipart/form-data
```

**Form Data:**
- `file` - The file (JPEG, PNG, PDF, max 10MB)
- `document_type` - One of the document types above
- `description` - Optional description

**Example using cURL:**
```bash
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/document.jpg" \
  -F "document_type=valid_id" \
  -F "description=Driver's License"
```

**Response (201):**
```json
{
    "status": "success",
    "message": "Document uploaded successfully",
    "data": {
        "id": "678abc...",
        "document_type": "valid_id",
        "original_filename": "drivers_license.jpg",
        "file_size": 245678,
        "file_size_display": "239.9 KB",
        "status": "pending",
        "uploaded_at": "2025-01-05T14:30:00Z"
    }
}
```

---

### 3. List Documents

```
GET /api/documents/
```

**Query Params (optional):**
- `type=valid_id` - Filter by document type

**Response:**
```json
{
    "status": "success",
    "data": {
        "documents": [
            {
                "id": "678abc...",
                "document_type": "valid_id",
                "original_filename": "drivers_license.jpg",
                "file_size": 245678,
                "status": "pending",
                "verified": false,
                "file_url": "/media/documents/123/valid_id/20250105_abc123.jpg",
                "uploaded_at": "2025-01-05T14:30:00Z"
            }
        ],
        "total": 1
    }
}
```

---

### 4. Get Document Details

```
GET /api/documents/<document_id>/
```

---

### 5. Delete Document

```
DELETE /api/documents/<document_id>/
```

> ⚠️ Cannot delete verified documents

---







## Loan Officer Endpoints

### 6. Verify Document

```
PUT /api/documents/<document_id>/verify/
```

**Headers:** `Authorization: Bearer <loan_officer_access_token>`

**Request Body (Approve):**
```json
{
    "action": "approve",
    "notes": "Document verified successfully"
}
```

**Request Body (Reject):**
```json
{
    "action": "reject",
    "rejection_reason": "Document is blurry and unreadable",
    "notes": "Please upload a clearer image"
}
```

---

## Testing Flow

1. **Login as customer** → Get access token
2. **Get document types** → `GET /api/documents/types/`
3. **Upload document** → `POST /api/documents/upload/`
4. **List documents** → `GET /api/documents/`
5. **Login as loan officer** → Get token
6. **Verify document** → `PUT /api/documents/<id>/verify/`

---

## Error Responses

### File Too Large
```json
{
    "status": "error",
    "message": "File size exceeds maximum allowed (10MB)"
}
```

### Invalid File Type
```json
{
    "status": "error",
    "message": "Invalid file type. Allowed types: JPEG, PNG, PDF"
}
```

### Cannot Delete Verified
```json
{
    "status": "error",
    "message": "Cannot delete verified documents"
}
```

---

## Section 2: CNN_FINAL_GUIDE.md

# CNN Document Classifier — Final Guide

> **⚠️ This document supersedes** `CNN_TRAINING_GUIDE.md`, `CNN_QUICK_START.md`, and `CNN_DOCUMENT_ANALYSIS.md`.
> Those files are now **deprecated** and should not be referenced for new work.

---

## What This Guide Covers

This is the single, authoritative reference for training, testing, and deploying the MobileNetV2-based CNN that classifies documents for Philippine MSME loan applications. It consolidates three earlier docs into one and covers:

| Section | Purpose |
|---------|---------|
| **System Overview** | Architecture, built-in features, current vs. future mode |
| **Document Classes & Folder Layout** | The 7 classes and where to put images |
| **How Many Images Do I Need?** | Dataset sizing, splits, class imbalance, plateau criteria |
| **Image Quality Requirements** | Lighting, angles, background, diversity checklist |
| **Where to Get Training Data** | Kaggle, Roboflow, MIDV-500, volunteers, synthetic data |
| **Privacy & Security** | Anonymization, consent, gitignore rules |
| **5-Day Quick Start Plan** | Day-by-day schedule for a production-ready model |
| **Training Process** | Prerequisites → validation → training → fine-tuning |
| **Testing Your Model** | Shell tests, API tests, confusion matrix script |
| **API Integration** | Request/response schemas for quality-check and CNN modes |
| **Quality Issues Reference** | Blur, brightness, size thresholds |
| **Improving Model Performance** | Data, architecture, training, and evaluation fixes |
| **Performance & Deployment** | File sizes, inference speed, production checklist |
| **Retraining Strategy** | When and how to retrain |
| **Philippine-Specific Tips** | ID types, permits, bills, selfie diversity |
| **Troubleshooting** | Common errors and fixes |
| **Helper Scripts Cheat Sheet** | One-liner commands for every utility script |
| **Additional Resources** | Papers, datasets, tools |

---

## 1 · System Overview

### Architecture

| Item | Value |
|------|-------|
| **Base model** | MobileNetV2 (transfer learning from ImageNet) |
| **Input size** | 224 × 224 RGB |
| **Classes** | 7 document types |
| **Training modes** | Transfer learning (backbone frozen) · Full fine-tuning |
| **Data augmentation** | Random horizontal flip, rotation ±10°, crop 256→224, color jitter ±20% |
| **Train / val split** | 80 / 20 |
| **Scheduler** | Learning rate scheduler + early stopping (saves best model) |

### Operating Modes

| Mode | When | What Happens |
|------|------|--------------|
| **Quality-check only** | No `.pth` model file present | Blur / brightness / size / aspect-ratio checks only |
| **CNN classification** | `document_classifier.pth` exists | Full classification (7 classes) + quality checks |

> **Current status:** Quality-check only (no trained model yet).
> The API automatically switches to CNN mode once the model file is present—no code changes required.

### Helper Scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_training_data.py` | Dataset health check — verifies folders, counts images, detects corrupt/small files |
| `scripts/anonymize_images.py` | Permanently blurs sensitive regions for privacy before training |
| `scripts/test_cnn_model.py` | Loads trained CNN and evaluates images/folders — reports type, confidence, quality, per-class accuracy |

---

## 2 · Document Classes & Folder Layout

```
documents/ml/training_data/
├── valid_id/           # Philippine government IDs (passport, DL, UMID, SSS)
├── selfie_with_id/     # Person holding their ID
├── business_permit/    # DTI / SEC / Mayor's permits
├── proof_of_address/   # Utility bills, barangay certificates
├── business_photo/     # Business storefront / premises
├── income_proof/       # Bank statements, receipts (optional class)
└── invalid/            # Negative samples — random photos, blurry docs, screenshots
```

Holdout test folder (create this manually before training):

```
documents/ml/test_data/
├── valid_id/
├── selfie_with_id/
├── business_permit/
├── proof_of_address/
├── business_photo/
├── income_proof/
└── invalid/
```

---

## 3 · How Many Images Do I Need?

### 3.1 Recommended Minimums Per Class

| Tier | Images / class | Total (7 classes) | Expected Val Accuracy | Use When |
|------|---------------|-------------------|----------------------|----------|
| 🟡 **Small (MVP)** | 40–50 | 280–350 | 70–80 % | Proof-of-concept, early testing |
| 🟢 **Medium** | 80–100 | 560–700 | 82–90 % | Beta deployment with officer review |
| 🌟 **Strong baseline** | 150–200+ | 1 000+ | 90–96 % | Production with high confidence |

#### Per-Class Breakdown

| Class | Small | Medium | Strong | Priority |
|-------|-------|--------|--------|----------|
| **valid_id** | 50 | 100 | 200+ | 🔴 Critical |
| **selfie_with_id** | 30 | 60 | 100+ | 🔴 Critical |
| **business_permit** | 40 | 80 | 150+ | 🟡 High |
| **proof_of_address** | 40 | 80 | 150+ | 🟡 High |
| **business_photo** | 30 | 60 | 100+ | 🟢 Medium |
| **income_proof** | 30 | 60 | 100+ | 🟢 Medium |
| **invalid** | 60 | 120 | 200+ | 🔴 Critical |

### 3.2 Train / Validation / Test Split

| Split | Ratio | Purpose |
|-------|-------|---------|
| **Train** | 64 % | Model learns from these |
| **Validation** | 16 % | Monitored during training; used for early stopping |
| **Test (holdout)** | 20 % | Never seen during training — final accuracy report |

> The built-in training script uses an **80 / 20 train / val** split automatically. You should **manually set aside ~20 % of your images as a holdout test set** *before* training, so the model never learns from them.

**Practical setup (required):**

1. Keep ~80 % of each class in `documents/ml/training_data/`.
2. Move ~20 % of each class to `documents/ml/test_data/` (holdout).
3. Run training as usual:
   ```bash
   python manage.py train_document_classifier
   ```
4. After training, run final evaluation on holdout only:
   ```bash
   python scripts/test_cnn_model.py documents/ml/test_data --confusion
   ```

**Example:** If a class has 100 images, put 80 in `training_data/` and 20 in `test_data/`.

### 3.3 How Class Imbalance Changes the Requirement

Class imbalance occurs when one class has far more images than another (e.g., `valid_id` has 200 but `income_proof` has 20).

| Imbalance Effect | What Happens |
|------------------|-------------|
| Majority-class bias | The model predicts the biggest class more often—even when wrong |
| Minority-class recall drops | Rare classes get very low per-class accuracy |
| Overall accuracy is misleading | 90 % overall can hide 40 % on the smallest class |

**Rules of thumb:**

1. **Keep classes within a 2:1 ratio.** If your largest class has 100 images, the smallest should have ≥ 50.
2. **Never let any class fall below 30 images** — the model cannot learn a reliable decision boundary with fewer.
3. If you *cannot* collect more data for a minority class, apply **heavier augmentation** (extra rotation, color jitter) for that class or use **class-weighted loss** in training.

### 3.4 What "Enough Data" Looks Like — Plateau Criteria

You have collected *enough* data when adding more images **does not meaningfully improve** validation accuracy. Use these signals:

| Signal | How to Check | "Enough" Threshold |
|--------|-------------|--------------------|
| **Accuracy plateau** | Plot val accuracy across retraining runs with 50 → 100 → 150 → 200 images per class | Curve flattens (< 1 % gain per 50 additional images) |
| **Confidence distribution** | Histogram of `type_confidence` on holdout set | ≥ 80 % of predictions have confidence > 0.85 |
| **Per-class recall** | Confusion matrix on holdout set | Every class ≥ 75 % recall |
| **Overfitting gap** | Train accuracy − val accuracy | Gap < 10 percentage points |

> **Practical advice:** Start with the "Small" tier, train, measure val accuracy, then iterate. If val accuracy jumps 5 %+ when you add 50 more images, you haven't plateaued yet — keep collecting.

---

## 4 · Image Quality Requirements

### Technical Specs

```yaml
Format:     JPEG or PNG (no PDFs for CNN)
Resolution: 224×224+ pixels (higher is better — auto-resized)
File size:  < 10 MB per image
Color:      RGB (grayscale is converted automatically)
```

### Diversity Checklist

Include all of the following variations to make the model generalize well:

| Category | Include ✅ | Exclude ❌ |
|----------|-----------|-----------|
| **Lighting** | Bright daylight · indoor (yellow/white) · flash · slightly dark · slight overexposure | Completely black images |
| **Angles** | Straight-on · slight tilt (±10–15°) · slight perspective rotation | Extreme angles (> 45°) |
| **Quality** | Sharp scans · clear phone photos · slight compression · minor blur · some JPEG artifacts | — |
| **Condition** | New docs · worn/creased · laminated vs. paper · photocopies · stamps/signatures | — |
| **Background** | White/plain · wooden table · fabric · cluttered (hands, papers) · outdoor (pavement, grass) | — |
| **Selfie-specific** | Different skin tones · with/without glasses · different expressions · indoor/outdoor · ID at different distances · portrait + landscape | — |

**Quality mix target:** 60 % high quality · 30 % medium · 10 % slightly low quality (but still readable).

---

## 5 · Where to Get Training Data

### Option 1 — Manual Collection (Best for Philippine Docs)

- Ask 10–20 volunteers via Google Forms + Drive.
- **Critical:** Blur names, addresses, ID numbers, signatures, and bank details *before* training.
- Philippine government websites often publish sample ID templates.

### Option 2 — Public Datasets

| Source | URL | Notes |
|--------|-----|-------|
| Kaggle | https://kaggle.com/datasets | Search "ID card dataset", "document classification" |
| Roboflow Universe | https://universe.roboflow.com | Search "ID document", "business card" |
| MIDV-500 / 2019 / 2020 | https://github.com/fcakyon/midv500 | 50 countries, multiple ID types including Asian IDs |
| Google Images | Search "Philippine passport sample" etc. | Last resort — only public-domain/sample images |

### Option 3 — Synthetic Data

For `proof_of_address` and `business_permit`:

1. Design realistic templates in Canva / Figma with varied fonts, layouts, colors.
2. Add realistic placeholder text.
3. Print and photograph at different angles and lighting.
4. Mix 50 % synthetic + 50 % real volunteers for best privacy/quality balance.

### Option 4 — Web Scraping (Legal Sources Only)

Always check `robots.txt` first. Only scrape public sample documents.

---

## 6 · Privacy & Security

### Rules

1. ✅ Get **explicit consent** from document owners.
2. ✅ **Anonymize** all personal information (names, addresses, ID numbers, signatures, photos on non-selfie docs, bank details).
3. ✅ Store training data **outside** the git repo.
4. ✅ Delete originals after training — keep only the `.pth` model.

### Recommended Workflow

```bash
# 1. Collect in a non-git temp folder
mkdir ~/msme_training_data_temp && cd ~/msme_training_data_temp

# 2. Organize by class
mkdir -p valid_id selfie_with_id business_permit proof_of_address \
         business_photo income_proof invalid

# 3. Anonymize
python scripts/anonymize_images.py ~/msme_training_data_temp/valid_id/

# 4. Copy to project for training
cp -r ~/msme_training_data_temp/* \
   ~/Capstone_Backend/documents/ml/training_data/

# 5. After training, delete both copies
rm -rf ~/msme_training_data_temp
rm -rf ~/Capstone_Backend/documents/ml/training_data/*/*.jpg
```

### Gitignore

```gitignore
# Training data (sensitive)
documents/ml/training_data/**/*
!documents/ml/training_data/**/README.md

# Model files (large)
documents/ml/models/*.pth
documents/ml/models/*.json
```

---

## 7 · 5-Day Quick Start Plan

| Day | Goal | Key Actions | Time |
|-----|------|-------------|------|
| **1** | Data collection | Collect 280+ images (40 / class). Use Kaggle, Roboflow, MIDV-500, volunteers. Prioritize: `invalid` → `valid_id` → `selfie_with_id` → permits → address → photo → income. | 4–6 h |
| **2** | Anonymization & validation | `scripts/anonymize_images.py` on all folders. Copy to `training_data/`. Run `scripts/check_training_data.py` — expect "✅ READY". | 3–4 h |
| **3** | First training run | `pip install torch torchvision pillow opencv-python`. `python manage.py train_document_classifier`. Target: 70–85 % val accuracy on first run. | 1–2 h |
| **4** | Improvement iteration | Add 20–40 more images to weak classes. Retrain with `--epochs 15`. If 80+ / class, try `--fine-tune`. | 4–6 h |
| **5** | Testing & deployment | Run `python scripts/test_cnn_model.py documents/ml/test_data --confusion` on holdout set. Verify API returns `"analysis_mode": "cnn"`. Delete training images from production. | 2–3 h |

---

## 8 · Training Process

### 8.1 Prerequisites

```bash
# CPU (good enough for MobileNetV2)
pip install torch torchvision pillow opencv-python

# GPU (optional, much faster)
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### 8.2 Verify Dataset

```bash
# Count images per class
for dir in documents/ml/training_data/*/; do
  echo "$(basename $dir): $(ls $dir/*.{jpg,jpeg,png} 2>/dev/null | wc -l)"
done
```

Or use the helper script:

```bash
python scripts/check_training_data.py
```

### 8.3 Train (Transfer Learning — Default)

```bash
python manage.py train_document_classifier
```

What this does:
- Freezes MobileNetV2 backbone (fast training)
- Trains only the classification head
- Batch size 32, 10 epochs
- Saves best model based on validation accuracy

### 8.4 Fine-Tuning (If Val Accuracy Plateaus Below 85 %)

Requires **100+ images per class** to avoid overfitting.

```bash
python manage.py train_document_classifier \
  --epochs 20 \
  --learning-rate 0.0001 \
  --fine-tune
```

### 8.5 Advanced Hyperparameter Tuning

```bash
# Larger batch size (GPU)
python manage.py train_document_classifier --epochs 15 --batch-size 64 --learning-rate 0.001

# Very small LR for fine-tuning
python manage.py train_document_classifier --epochs 25 --learning-rate 0.00005 --fine-tune
```

### 8.6 Reading Training Output

```
Epoch  1/10 — Train Loss: 1.234  Train Acc: 65.2% — Val Loss: 0.988  Val Acc: 72.5%
...
Epoch 10/10 — Train Loss: 0.346  Train Acc: 92.3% — Val Loss: 0.543  Val Acc: 87.5%
✅ Training complete! Best validation accuracy: 87.50%
```

| Val Accuracy | Interpretation |
|-------------|---------------|
| < 70 % | Need more data or longer training |
| 70–85 % | Good — ready for testing |
| 85–95 % | Excellent — production-ready ✅ |
| > 95 % | Outstanding (or possibly overfitting — check train/val gap) |

---

## 9 · Testing Your Model

### Test 1 — Verify Model Loads

```python
# python manage.py shell
from documents.services.analyzer import get_analyzer

analyzer = get_analyzer()
print(f"Model loaded: {analyzer.model_loaded}")  # → True
```

### Test 2 — Classify a Single Image

```python
from documents.services.analyzer import analyze_document

result = analyze_document('/path/to/test_id.jpg', expected_type='valid_id')
print(result)
# {
#   'is_valid': True,
#   'quality_score': 0.85,
#   'quality_issues': [],
#   'predicted_type': 'valid_id',
#   'type_confidence': 0.92,
#   'model_available': True,
#   'analysis_mode': 'cnn'
# }
```

### Test 3 — API Integration

```bash
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@test_id.jpg" \
  -F "document_type=valid_id"
```

Look for `"analysis_mode": "cnn"` and `"type_confidence"` in the response.

### Test 4 — Confusion Matrix (Holdout Set)

```bash
python scripts/test_cnn_model.py documents/ml/test_data/ --confusion
```

Or use this inline script:

```python
import os
from pathlib import Path
from documents.services.analyzer import analyze_document
from collections import defaultdict

test_dir = Path('documents/ml/test_data')
results = defaultdict(lambda: {'correct': 0, 'wrong': 0})

for class_dir in test_dir.iterdir():
    if not class_dir.is_dir():
        continue
    true_label = class_dir.name
    for img_path in class_dir.glob('*.jpg'):
        result = analyze_document(str(img_path), expected_type=true_label)
        predicted = result['predicted_type']
        if predicted == true_label:
            results[true_label]['correct'] += 1
        else:
            results[true_label]['wrong'] += 1
            print(f"❌ {img_path.name}: Expected {true_label}, got {predicted}")

for cls, counts in results.items():
    total = counts['correct'] + counts['wrong']
    accuracy = (counts['correct'] / total * 100) if total > 0 else 0
    print(f"{cls}: {accuracy:.1f}% ({counts['correct']}/{total})")
```

---

## 10 · API Integration

### Upload Endpoint

```http
POST /api/documents/upload/
Content-Type: multipart/form-data

file: <document_image>
document_type: "valid_id"
```

### Response — Quality-Check Mode (No Model)

```json
{
  "status": "success",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "document_type": "valid_id",
    "status": "pending",
    "ai_analysis": {
      "quality_score": 0.85,
      "is_valid": true,
      "quality_issues": [],
      "analysis_mode": "quality_check",
      "model_available": false
    }
  }
}
```

### Response — CNN Mode (Trained Model)

```json
{
  "status": "success",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "document_type": "valid_id",
    "status": "pending",
    "ai_analysis": {
      "predicted_type": "valid_id",
      "type_confidence": 0.92,
      "quality_score": 0.85,
      "is_valid": true,
      "quality_issues": [],
      "analysis_mode": "cnn",
      "model_available": true
    }
  }
}
```

### Quality Issues Reference

| Issue | Threshold | Description |
|-------|-----------|-------------|
| `Image too small` | < 224×224 | Below minimum CNN input size |
| `Image appears blurry` | Laplacian variance < 100 | Low sharpness |
| `Image too dark` | Brightness < 40 | Underexposed |
| `Image too bright` | Brightness > 240 | Overexposed / washed out |
| `Unusual aspect ratio` | > 5 : 1 | Possibly incorrectly cropped |

---

## 11 · Improving Model Performance

### Low Val Accuracy (< 75 %)

| Cause | Solution |
|-------|----------|
| Insufficient data | Collect 50+ images per class |
| Class imbalance | Balance class counts to within 2:1 ratio |
| Poor image quality | Remove completely blurry / corrupted images |
| Training too short | Increase epochs: `--epochs 20` |

### Overfitting (Train Acc >> Val Acc, Gap > 20 %)

| Solution | How |
|----------|-----|
| More data | Best fix — add real images |
| Stronger augmentation | `RandomRotation(15)`, `ColorJitter(0.3, 0.3)` |
| More dropout | `nn.Dropout(p=0.4)` in `cnn_model.py` |
| Fewer epochs | `--epochs 8` |

### Slow Training

| Solution | How |
|----------|-----|
| Use GPU | `python -c "import torch; print(torch.cuda.is_available())"` |
| Smaller batch size | `--batch-size 16` |
| CPU-optimized PyTorch | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu` |

---

## 12 · Performance & Deployment

### Model Specs

| Metric | Value |
|--------|-------|
| Model file (`document_classifier.pth`) | ~15–20 MB |
| Config file (`model_config.json`) | < 1 KB |
| RAM usage | ~50 MB |
| Temp memory per inference | ~10 MB |
| CPU inference | 100–200 ms / image |
| GPU inference | 10–30 ms / image |

### Production Deployment Checklist

- [ ] Overall validation accuracy ≥ 85 %
- [ ] No class below 75 % accuracy
- [ ] Tested on 20+ real-world images **not** in training set
- [ ] Confusion matrix shows no critical failures
- [ ] Model file size < 50 MB
- [ ] API integration tested (`"analysis_mode": "cnn"`)
- [ ] Inference time < 200 ms (CPU)
- [ ] All training data anonymized
- [ ] Training images **deleted** from production server
- [ ] Model files added to `.gitignore`
- [ ] Fallback to quality-check mode works if model fails to load

---

## 13 · Retraining Strategy

### When to Retrain

1. User feedback indicates recurring misclassifications.
2. New document types or formats appear (e.g., new PH ID design).
3. After collecting 100+ new images.
4. Every ~6 months as a maintenance cycle.

### How to Retrain

```bash
# Add new images to existing class folders
cp new_images/* documents/ml/training_data/valid_id/

# Retrain from scratch (recommended)
python manage.py train_document_classifier --epochs 15
```

> **Note:** Continuing from a previous checkpoint (incremental training) requires code modification to load prior weights. Retraining from scratch with the full dataset is simpler and typically gives better results.

---

## 14 · Philippine-Specific Tips

### `valid_id` (Most Critical)

- **Include:** Philippine Passport (20), Driver's License — old blue + new card (15), UMID (15), SSS ID (10)
- **Variations:** Front + back (separate images), laminated vs. paper, old vs. new designs

### `business_permit` (High Priority)

- **Include:** DTI Registration (30), Mayor's Permit — various municipalities (20), SEC Certificate (15), Barangay Clearance with business info (15)
- **Tip:** Different cities have different formats — collect variety!

### `proof_of_address`

- **Include:** Meralco bills (30), Water bills — various providers (20), Barangay Certificate of Residency (15), Internet bills — PLDT, Converge, Sky (15)

### `selfie_with_id`

- 50 / 50 male / female
- Various ages (20–60)
- Different skin tones (Filipino diversity)
- Indoor / outdoor lighting (70 / 30)

### `invalid`

- **Do not skip this class!** Without negatives the model classifies *anything* as a valid document.
- Include: landscapes, food, animals, text-only screenshots, random photos.

---

## 15 · Troubleshooting

| Error / Symptom | Fix |
|-----------------|-----|
| `PyTorch not installed` | `pip install torch torchvision pillow opencv-python` |
| `Training data folder not found` | Verify `documents/ml/training_data/` contains 7 sub-folders |
| `Only X training samples found` | Need ≥ 50 images total across all classes |
| `CUDA out of memory` | `python manage.py train_document_classifier --batch-size 8` |
| Model won't load (API still shows `quality_check`) | 1) Check `.pth` file exists 2) `chmod 644` 3) Restart Django 4) `tail -f logs/documents.log` |
| Accuracy stuck at 60–70 % | 1) Run `check_training_data.py` 2) Add 20+ images to weakest classes 3) Try `--epochs 15` |
| Training too slow | Reduce batch size to 16 · Use CPU-optimized PyTorch · Train fewer epochs initially |

---

## 16 · Helper Scripts Cheat Sheet

```bash
# Validate dataset
python scripts/check_training_data.py

# Anonymize single image
python scripts/anonymize_images.py path/to/image.jpg

# Anonymize entire folder (batch)
python scripts/anonymize_images.py path/to/folder/ --batch

# Test single image
python scripts/test_cnn_model.py test_image.jpg

# Test folder of images
python scripts/test_cnn_model.py test_folder/ --batch

# Confusion matrix on labeled holdout set
python scripts/test_cnn_model.py documents/ml/test_data/ --confusion
```

---

## 17 · Realistic Accuracy Expectations

| Target | Status | Notes |
|--------|--------|-------|
| **100 %** | ❌ Impossible | Real-world edge cases are infinite |
| **95–98 %** | 🌟 Exceptional | Requires 200+ samples / class |
| **90–95 %** | ✅ Excellent | Achievable with 100+ samples / class |
| **85–90 %** | ✅ Good | Achievable with 50+ samples / class |
| **< 85 %** | ⚠️ Needs work | Add more training data |

**Why not 100 %?** Lighting variations, user photo angles, document quality (old / photocopied), edge cases (foreign IDs, non-standard formats), class overlap (business permits can look like address proofs).

**Your safety net:** Even misclassified documents go through manual loan-officer review!

---

## 18 · Additional Resources

### Research & Tutorials

- **MobileNetV2 paper:** https://arxiv.org/abs/1801.04381
- **Transfer learning tutorial:** https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html
- **Data augmentation transforms:** https://pytorch.org/vision/stable/transforms.html
- **Document classification benchmarks:** https://paperswithcode.com/task/document-image-classification

### Datasets

| Source | URL |
|--------|-----|
| Kaggle | https://kaggle.com/datasets |
| Roboflow Universe | https://universe.roboflow.com |
| MIDV-500 | https://github.com/fcakyon/midv500 |

### Tools

| Tool | URL |
|------|-----|
| Online image anonymization | https://cleanup.pictures |
| Bulk image resizing | https://www.imagemagick.org |

---

## Section 3: CNN_DOCUMENT_ANALYSIS.md

# Document Analysis (CNN) Guide

## Overview

AI-powered document analysis for uploaded documents using **MobileNetV2 CNN** with transfer learning.

**Current Mode:** Quality-check only (no trained model yet)  
**Future Mode:** CNN classification with 7 document classes  
**Target Accuracy:** 85-95% (production-ready)

CNN purpose: Document classification

- check_training_data: It’s a dataset health check: verifies your class folders exist, counts images, detects small/corrupt files, and tells you if you have enough data to train your CNN.

- Anonymize_images: It permanently blurs sensitive regions in images for privacy before training, which is safe for document-type classification if applied consistently, but it cannot teach the model to judge image quality or blur, since the original details are destroyed.

- test_cnn_model: This script loads your already-trained CNN and evaluates it on images or folders to report predicted document type, confidence, quality signals, and per-class accuracy, without doing any training or modifying the images itself.

---

## Quick Links

📚 **[Complete CNN Training Guide](#section-5-cnn_training_guidemd)** - Everything you need to know  
✅ **[Data Collection Checklist](../documents/ml/training_data/DATA_COLLECTION_CHECKLIST.md)** - Track your progress  
🔧 **Helper Scripts:**
- `scripts/check_training_data.py` - Validate your dataset before training
- `scripts/anonymize_images.py` - Blur personal information in images
- `scripts/test_cnn_model.py` - Test trained model accuracy

---

## Features

### Quality Check (Active Now) ✅
- **Blur detection** using Laplacian variance
- **Brightness validation** (too dark/bright detection)
- **Size validation** (minimum 224x224 pixels)
- **Aspect ratio check** (prevents badly cropped images)
- **Auto-flags** low-quality documents for manual review

### CNN Classification (After Training) 🎯
- **7 document types:** valid_id, selfie_with_id, business_permit, proof_of_address, business_photo, income_proof, invalid
- **Confidence scoring** (0-100%)
- **Invalid document detection** (negative samples)
- **Transfer learning** from ImageNet-pretrained MobileNetV2

---

## Training Data Requirements

### Recommended Dataset Size

| Class | Minimum | Good | Excellent |
|-------|---------|------|-----------|
| valid_id | 50 | 100 | 200+ |
| selfie_with_id | 30 | 60 | 100+ |
| business_permit | 40 | 80 | 150+ |
| proof_of_address | 40 | 80 | 150+ |
| business_photo | 30 | 60 | 100+ |
| income_proof | 30 | 60 | 100+ |
| invalid | 60 | 120 | 200+ |
| **TOTAL** | **280** | **560** | **1000+** |

### Where to Get Training Data

1. **Kaggle Datasets**
   - Search: "ID card dataset", "document classification"
   - https://kaggle.com/datasets

2. **Roboflow Universe**
   - Search: "ID document", "business card"
   - https://universe.roboflow.com

3. **MIDV-500/2019/2020**
   - Research dataset with 50 countries
   - https://github.com/fcakyon/midv500

4. **Volunteer Collection** (Best for Philippine docs)
   - Create Google Form for consent + upload
   - Collect real Philippine IDs, permits, bills
   - **CRITICAL:** Anonymize all personal info!

### Where to Put Training Data

```
documents/ml/training_data/
├── valid_id/           # Philippine government IDs
├── selfie_with_id/     # Person holding ID
├── business_permit/    # DTI/SEC/Mayor's permits
├── proof_of_address/   # Utility bills, barangay certs
├── business_photo/     # Business storefront photos
├── income_proof/       # Bank statements, receipts
└── invalid/            # Bad images (negative samples)
```

**Image requirements:**
- Format: JPEG or PNG
- Resolution: 224x224+ pixels (higher is better)
- Quality: Mix of high/medium/low quality for robustness
- Diversity: Vary lighting, angles, backgrounds

See [DATA_COLLECTION_CHECKLIST.md](../documents/ml/training_data/DATA_COLLECTION_CHECKLIST.md) for detailed requirements.

---

## Training Process

### Step 1: Validate Dataset

```bash
# Check if you have enough images
python scripts/check_training_data.py
```

Expected output:
```
✅ valid_id          100 images  (avg size: 2048x1536)
✅ selfie_with_id     60 images  (avg size: 1920x1080)
...
✅ READY FOR TRAINING!
   560 images collected across 7 classes
```

### Step 2: Install Dependencies

```bash
pip install torch torchvision pillow opencv-python
```

### Step 3: Train Model

```bash
# Default settings (good for 50-100 images per class)
python manage.py train_document_classifier
```

**Training options:**
```bash
# More epochs for better accuracy
python manage.py train_document_classifier --epochs 20

# Smaller batch size if memory is limited
python manage.py train_document_classifier --batch-size 16

# Full fine-tuning (requires 100+ images per class)
python manage.py train_document_classifier --fine-tune
```

### Step 4: Monitor Training

Watch for validation accuracy to reach **85-95%**:

```
Epoch 1/10 - Train Loss: 1.2340, Train Acc: 65.23% - Val Loss: 0.9876, Val Acc: 72.50%
Epoch 2/10 - Train Loss: 0.8765, Train Acc: 78.91% - Val Loss: 0.7654, Val Acc: 81.25%
...
Epoch 10/10 - Train Loss: 0.3456, Train Acc: 92.34% - Val Loss: 0.5432, Val Acc: 87.50%
✅ Training complete! Best validation accuracy: 87.50%
```

**Interpretation:**
- **<70%:** Need more training data
- **70-85%:** Good, ready for testing
- **85-95%:** Excellent, production-ready! ✅
- **>95%:** Outstanding (or overfitting)

### Step 5: Test Model

```bash
# Test single image
python scripts/test_cnn_model.py ~/Downloads/my_id.jpg

# Test batch of images
python scripts/test_cnn_model.py ~/test_images/ --batch

# Confusion matrix (requires labeled test data)
python scripts/test_cnn_model.py documents/ml/test_data/ --confusion
```

### Output Files

After successful training:
- `documents/ml/models/document_classifier.pth` (~15-20MB)
- `documents/ml/models/model_config.json` (<1KB)

---

## API Integration

### Upload Endpoint Response

```http
POST /api/documents/upload/
Content-Type: multipart/form-data

file: <document_image>
document_type: "valid_id"
```

**Response (Quality-check mode - Before training):**
```json
{
  "status": "success",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "document_type": "valid_id",
    "status": "pending",
    "ai_analysis": {
      "quality_score": 0.85,
      "is_valid": true,
      "quality_issues": [],
      "analysis_mode": "quality_check",
      "model_available": false
    }
  }
}
```

**Response (CNN mode - After training):**
```json
{
  "status": "success",
  "data": {
    "id": "507f1f77bcf86cd799439011",
    "document_type": "valid_id",
    "status": "pending",
    "ai_analysis": {
      "predicted_type": "valid_id",
      "type_confidence": 0.92,
      "quality_score": 0.85,
      "is_valid": true,
      "quality_issues": [],
      "analysis_mode": "cnn",
      "model_available": true
    }
  }
}
```

### Quality Issues Detected

| Issue | Threshold | Description |
|-------|-----------|-------------|
| `Image too small` | <224x224 | Below minimum CNN input size |
| `Image appears blurry` | Variance <100 | Low Laplacian variance (sharpness) |
| `Image too dark` | Brightness <40 | Underexposed image |
| `Image too bright` | Brightness >240 | Overexposed/washed out |
| `Unusual aspect ratio` | >5:1 | May be incorrectly cropped |

---

## Privacy & Security

### Critical Rules ⚠️

1. **Never commit training data to git**
   - Add `documents/ml/training_data/**/*` to `.gitignore`
   - Only keep README files in version control

2. **Anonymize all images before training**
   ```bash
   # Use the anonymization script
   python scripts/anonymize_images.py ~/training_data/valid_id/
   ```

3. **Blur personal information:**
   - Names, addresses, ID numbers
   - Signatures, photos (for non-selfie docs)
   - Bank account numbers, amounts

4. **Get explicit consent**
   - Use consent forms for volunteer collection
   - Explain data will be anonymized
   - Delete originals after training

---

## Troubleshooting

### Model Not Loading

**Symptom:** API shows `"analysis_mode": "quality_check"` after training

**Solutions:**
1. Check model file exists:
   ```bash
   ls -lh documents/ml/models/document_classifier.pth
   # Should show ~15-20MB file
   ```

2. Check file permissions:
   ```bash
   chmod 644 documents/ml/models/document_classifier.pth
   ```

3. Restart Django:
   ```bash
   python manage.py runserver
   ```

4. Check logs:
   ```bash
   tail -f logs/documents.log
   # Look for "CNN model loaded successfully" or errors
   ```

### Low Training Accuracy (<85%)

**Possible causes:**
1. **Insufficient training data**
   - Solution: Collect 80+ images per class

2. **Class imbalance**
   - Check: Run `python scripts/check_training_data.py`
   - Solution: Balance class counts (similar quantities)

3. **Poor image quality**
   - Solution: Remove completely blurry/corrupted images

4. **Overfitting** (train acc >> val acc)
   - Solution: Add more training data or reduce epochs

### Training Errors

**Error: "PyTorch not installed"**
```bash
pip install torch torchvision
```

**Error: "CUDA out of memory"**
```bash
# Reduce batch size
python manage.py train_document_classifier --batch-size 8
```

**Error: "Too few training samples"**
- Need at least 50 total images across all classes
- Recommended: 280+ images (40 per class)

---

## Performance Expectations

### Inference Speed
- **CPU:** 100-200ms per image
- **GPU:** 10-30ms per image
- **Memory:** ~50MB RAM for model

### Model Size
- **document_classifier.pth:** 15-20MB (MobileNetV2 is lightweight)
- **model_config.json:** <1KB

### Accuracy Targets
- **85-90%:** Good (production-ready for beta)
- **90-95%:** Excellent (production-ready)
- **95%+:** Outstanding (requires extensive data)

**Note:** Even 85% accuracy is sufficient because:
- Quality-check fallback catches issues
- Loan officers manually review all documents
- False positives only affect auto-categorization, not approval

---

## Next Steps

1. **Read the complete guide:**
   - [CNN Training Guide](#section-5-cnn_training_guidemd) - Comprehensive training documentation

2. **Collect training data:**
   - Follow [DATA_COLLECTION_CHECKLIST.md](../documents/ml/training_data/DATA_COLLECTION_CHECKLIST.md)
   - Target: 560+ images (80 per class)

3. **Validate dataset:**
   ```bash
   python scripts/check_training_data.py
   ```

4. **Train model:**
   ```bash
   python manage.py train_document_classifier
   ```

5. **Test accuracy:**
   ```bash
   python scripts/test_cnn_model.py documents/ml/test_data/ --confusion
   ```

6. **Deploy:**
   - Model auto-loads when `.pth` file exists
   - API automatically switches to CNN mode
   - No code changes needed!

---

## Additional Resources

### Research Papers
- **MobileNetV2:** https://arxiv.org/abs/1801.04381
- **Transfer Learning:** https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html

### Datasets
- **Kaggle:** https://kaggle.com/datasets (search "document classification")
- **Roboflow:** https://universe.roboflow.com
- **Papers with Code:** https://paperswithcode.com/task/document-image-classification

### Tools
- **Data Augmentation:** https://pytorch.org/vision/stable/transforms.html
- **Image Anonymization:** https://cleanup.pictures (online tool)
- **Bulk Resizing:** https://www.imagemagick.org

---

## Section 4: CNN_QUICK_START.md

# CNN Training Quick Start Guide
## Get Your Model to 90% Accuracy FAST

> **Goal:** Train a production-ready document classifier in 3-5 days

---

## 📅 5-Day Training Plan

### Day 1: Data Collection (Minimum Viable Dataset)
**Goal:** Collect 280+ images (40 per class)

**Priority order:**
1. ✅ **invalid** (60 images) - Random photos, blurry docs, screenshots
2. ✅ **valid_id** (50 images) - Philippine IDs (passport, driver's license, UMID)
3. ✅ **selfie_with_id** (30 images) - People holding IDs
4. ✅ **business_permit** (40 images) - DTI, SEC, Mayor's permits
5. ✅ **proof_of_address** (40 images) - Utility bills, barangay certs
6. ✅ **business_photo** (30 images) - Storefront photos
7. ✅ **income_proof** (30 images) - Bank statements, receipts

**Sources (pick 2-3):**
- Kaggle: https://kaggle.com/datasets (search "ID document dataset")
- Roboflow: https://universe.roboflow.com
- Google Forms: Collect from 10-15 volunteers
- MIDV-500: https://github.com/fcakyon/midv500

**Time estimate:** 4-6 hours

### Day 2: Anonymization & Validation
**Goal:** Blur personal info and validate dataset

```bash
# 1. Blur sensitive information
python scripts/anonymize_images.py ~/training_data_temp/valid_id/

# 2. Move to project folder
cp -r ~/training_data_temp/* documents/ml/training_data/

# 3. Validate dataset
python scripts/check_training_data.py

# 4. Should see:
# ✅ READY FOR TRAINING!
#    280+ images collected across 7 classes
```

**Time estimate:** 3-4 hours

### Day 3: First Training Run
**Goal:** Train baseline model and identify issues

```bash
# 1. Install dependencies
pip install torch torchvision pillow opencv-python

# 2. Train model (default settings)
python manage.py train_document_classifier

# 3. Watch for validation accuracy
# Target: 75-85% on first run
```

**Expected results:**
- Validation accuracy: 70-85%
- Training time: 10-30 minutes
- Output: `documents/ml/models/document_classifier.pth`

**If accuracy <70%:**
- Check for corrupted images
- Balance class counts
- Collect 10-20 more images per weak class

**Time estimate:** 1-2 hours

### Day 4: Improvement Iteration
**Goal:** Boost accuracy to 85-90%

**Strategy A: More Data (Best approach)**
```bash
# Collect 20-40 more images per class
# Focus on classes with low accuracy

# Retrain
python manage.py train_document_classifier --epochs 15
```

**Strategy B: Fine-tuning (If you have 80+ per class)**
```bash
python manage.py train_document_classifier \
  --epochs 20 \
  --learning-rate 0.0001 \
  --fine-tune
```

**Time estimate:** 4-6 hours (mostly data collection)

### Day 5: Testing & Deployment
**Goal:** Verify accuracy and deploy

```bash
# 1. Test model on holdout images
python scripts/test_cnn_model.py ~/test_images/ --confusion

# 2. Check per-class accuracy
# All classes should be 80%+

# 3. Test via API
curl -X POST http://localhost:8000/api/documents/upload/ \
  -F "file=@test_id.jpg" \
  -F "document_type=valid_id" \
  -H "Authorization: Bearer YOUR_TOKEN"

# 4. Verify response includes CNN results:
# "analysis_mode": "cnn"
# "type_confidence": 0.92
```

**Deployment checklist:**
- [ ] Overall accuracy ≥85%
- [ ] All classes ≥75%
- [ ] Tested 20+ real-world images
- [ ] API integration working
- [ ] Training data deleted from production

**Time estimate:** 2-3 hours

---

## 🎯 Minimum Requirements

| Requirement | Target | Why |
|-------------|--------|-----|
| **Total images** | 280+ | Minimum for training |
| **Per class** | 40+ | Prevent class imbalance |
| **Invalid class** | 60+ | Critical for "not a document" detection |
| **Image size** | 224x224+ | CNN input requirement |
| **Quality mix** | 60% high, 30% medium, 10% low | Real-world diversity |
| **Lighting mix** | Bright/indoor/dark | Generalization |

---

## 🚀 Fast Track Options

### Option 1: Use Kaggle Dataset (Fastest)
**Time:** 1 hour setup + 30 min training

```bash
# 1. Find "document classification" dataset on Kaggle
# 2. Download (usually 500-1000 images)
# 3. Organize into 7 folders
# 4. Train immediately

# Pros: Fast, large dataset
# Cons: May not have Philippine-specific docs
```

### Option 2: Synthetic + Real Mix
**Time:** 2-3 days

```bash
# 1. Generate 50% synthetic documents (Canva/Figma templates)
# 2. Collect 50% real volunteers (20-30 images)
# 3. Combine for 300+ total

# Pros: Privacy-friendly, faster than pure collection
# Cons: Synthetic may not capture all real-world variations
```

### Option 3: Pre-trained Transfer (Advanced)
**Time:** 1 day (if you have ImageNet weights)

```bash
# Use MobileNetV2 pre-trained weights
# Only train classifier head
# Requires 50-100 images per class

python manage.py train_document_classifier --epochs 8

# Pros: Fastest training, good accuracy
# Cons: May overfit with limited data
```

---

## 📊 Expected Accuracy by Dataset Size

| Dataset Size | Expected Val Accuracy | Status |
|--------------|----------------------|--------|
| 150-250 images | 65-75% | ⚠️ Too small, needs more data |
| 280-400 images | 75-85% | ✅ MVP, production-ready |
| 400-600 images | 85-92% | ✅✅ Excellent |
| 600-1000+ images | 90-96% | 🌟 Outstanding |

---

## 🔧 Helper Scripts Cheat Sheet

```bash
# Check if dataset is ready
python scripts/check_training_data.py

# Blur personal info (interactive)
python scripts/anonymize_images.py path/to/image.jpg

# Blur all images in folder (batch mode)
python scripts/anonymize_images.py path/to/folder/ --batch

# Test single image
python scripts/test_cnn_model.py test_image.jpg

# Test batch
python scripts/test_cnn_model.py test_folder/ --batch

# Confusion matrix
python scripts/test_cnn_model.py test_data/ --confusion
```

---

## 🎓 Philippine-Specific Tips

### For `valid_id` (Most Critical)
**Must include:**
- 20 images: Philippine Passport (different formats)
- 15 images: Driver's License (old blue + new card)
- 15 images: UMID (common for MSMEs)
- 10 images: SSS ID

**Variations:**
- Front + back (count as separate images)
- Laminated vs. paper
- Old vs. new designs

### For `business_permit` (High Priority)
**Must include:**
- 30 images: DTI Business Registration (most common)
- 20 images: Mayor's Permit (various municipalities)
- 15 images: SEC Certificate (corporations)
- 15 images: Barangay Clearance with business info

**Tip:** Different cities have different formats - collect variety!

### For `proof_of_address`
**Must include:**
- 30 images: Meralco bills (most common in Metro Manila)
- 20 images: Water bills (various local providers)
- 15 images: Barangay Certificate of Residency
- 15 images: Internet bills (PLDT, Converge, Sky)

### For `selfie_with_id`
**Diversity requirements:**
- 50/50 male/female
- Various ages (20-60)
- Different skin tones (Filipino diversity)
- Indoor/outdoor lighting (70/30)

---

## ⚠️ Common Mistakes to Avoid

### 1. Skipping the `invalid` Class
❌ Don't skip this!  
✅ Collect 60+ random images (landscapes, food, animals, text-only docs)

**Why:** Without negatives, model will classify **anything** as a valid document.

### 2. Using Only High-Quality Images
❌ All sharp, well-lit photos  
✅ Mix: 60% high, 30% medium, 10% slightly blurry

**Why:** Real users upload phone photos with varying quality.

### 3. Single Lighting Condition
❌ All photos in bright daylight  
✅ Mix: bright, indoor, flash, slightly dark

**Why:** Users take photos in different environments.

### 4. Not Balancing Classes
❌ valid_id: 200 images, income_proof: 20 images  
✅ All classes within 50% of each other (40-80 range)

**Why:** Model will bias towards majority class.

### 5. Training Too Long (Overfitting)
❌ 50 epochs with 40 images per class  
✅ 10-15 epochs, watch validation accuracy

**Why:** Small datasets overfit quickly.

### 6. Forgetting to Anonymize
❌ Training with real names/addresses visible  
✅ Blur all personal information first

**Why:** Privacy violations, potential data leaks.

---

## 🏆 Success Criteria

**Your model is production-ready when:**

- [ ] Overall validation accuracy ≥85%
- [ ] No class below 75% accuracy
- [ ] Tested on 20+ real-world images (not from training set)
- [ ] API returns `"analysis_mode": "cnn"`
- [ ] Confusion matrix shows no critical failures
- [ ] Model file size <50MB
- [ ] Inference time <200ms (CPU)
- [ ] All training data anonymized
- [ ] Training images deleted from production server

---

## 📞 Need Help?

### If accuracy is stuck at 60-70%:
1. Run `python scripts/check_training_data.py` - look for imbalances
2. Add 20+ more images to weakest classes
3. Try `--epochs 15` instead of default 10

### If training is too slow:
1. Reduce batch size: `--batch-size 16`
2. Use CPU-optimized PyTorch
3. Train on fewer epochs initially (5-8)

### If model won't load:
1. Check `ls -lh documents/ml/models/document_classifier.pth`
2. Restart Django server
3. Check logs: `tail -f logs/documents.log`

---

## 📚 Additional Resources

**Full documentation:**
- [CNN Training Guide](#section-5-cnn_training_guidemd) - Complete training guide
- [DATA_COLLECTION_CHECKLIST.md](../documents/ml/training_data/DATA_COLLECTION_CHECKLIST.md) - Detailed checklist
- [CNN Document Analysis](#section-3-cnn_document_analysismd) - API integration guide

**Datasets:**
- Kaggle: https://kaggle.com/datasets
- Roboflow: https://universe.roboflow.com
- MIDV-500: https://github.com/fcakyon/midv500

**Tools:**
- Anonymization: https://cleanup.pictures
- Bulk resize: https://www.imagemagick.org
- Data augmentation: https://pytorch.org/vision/stable/transforms.html

---

**Ready to start? Run:**
```bash
python scripts/check_training_data.py
```

**And follow the day-by-day plan above!** 🚀

---

## Section 5: CNN_TRAINING_GUIDE.md

# CNN Document Classifier - Complete Training Guide

> **Goal:** Train a MobileNetV2-based CNN to classify 7 document types for Philippine MSME loan applications

---

## 📊 System Analysis

### Current Architecture
- **Model:** MobileNetV2 (transfer learning from ImageNet)
- **Input size:** 224x224 RGB images
- **Classes:** 7 document types
- **Training mode:** Transfer learning (backbone frozen) or full fine-tuning
- **Data augmentation:** Built-in (rotation, flip, crop, color jitter)

### Built-in Features ✅
Your training script already includes:
- ✅ Random horizontal flip
- ✅ Random rotation (±10°)
- ✅ Random crop (256→224)
- ✅ Color jitter (brightness/contrast ±20%)
- ✅ 80/20 train/validation split
- ✅ Learning rate scheduler
- ✅ Early stopping (saves best model)

---

## 🎯 Realistic Accuracy Expectations

| Target Accuracy | Status | Notes |
|-----------------|--------|-------|
| **100%** | ❌ Impossible | Real-world has infinite edge cases |
| **95-98%** | 🌟 Exceptional | Requires 200+ samples per class |
| **90-95%** | ✅ Excellent | Achievable with 100+ samples per class |
| **85-90%** | ✅ Good | Achievable with 50+ samples per class |
| **<85%** | ⚠️ Needs more data | Add more training samples |

**Why not 100%?**
- Lighting variations (indoor/outdoor, flash/no flash)
- User photo angles (tilted, perspective distortion)
- Document quality (old/new, damaged, photocopied)
- Edge cases (foreign IDs, non-standard formats)
- Class overlap (business permits can look similar to address proof)

**Your safety net:** Even misclassified documents go through manual loan officer review!

---

## 📁 Required Training Data

### Document Classes (7 types)

```
documents/ml/training_data/
├── valid_id/           # Philippine government IDs
├── selfie_with_id/     # Person holding ID
├── business_permit/    # DTI/SEC/Mayor's permits
├── proof_of_address/   # Utility bills, barangay cert
├── business_photo/     # Business storefront/premises
├── income_proof/       # Bank statements, receipts (optional)
└── invalid/            # Bad images (negative samples)
```

### Recommended Dataset Sizes

| Class | Minimum | Good | Excellent | Priority |
|-------|---------|------|-----------|----------|
| **valid_id** | 50 | 100 | 200+ | 🔴 Critical |
| **selfie_with_id** | 30 | 60 | 100+ | 🔴 Critical |
| **business_permit** | 40 | 80 | 150+ | 🟡 High |
| **proof_of_address** | 40 | 80 | 150+ | 🟡 High |
| **business_photo** | 30 | 60 | 100+ | 🟢 Medium |
| **income_proof** | 30 | 60 | 100+ | 🟢 Medium |
| **invalid** | 60 | 120 | 200+ | 🔴 Critical |

**Total minimum:** 280 images  
**Total recommended:** 560-1000+ images

---

## 🖼️ Image Quality Requirements

### Technical Specs
```yaml
Format: JPEG, PNG (no PDFs for CNN)
Resolution: 224x224+ pixels (higher is better, will be resized)
File size: <10MB per image
Color: RGB (no grayscale, system converts automatically)
```

### Quality Variations to Include

Your CNN **MUST train on diverse quality levels** to generalize well:

#### 1. **Lighting Conditions** (Critical)
- ✅ Bright daylight photos
- ✅ Indoor lighting (yellow/white)
- ✅ Flash photography
- ✅ Slightly dark images (not pitch black)
- ✅ Slight overexposure
- ❌ Don't include: Completely black images

#### 2. **Angles & Orientation** (Critical)
- ✅ Straight-on shots (ideal)
- ✅ Slight tilt (±10-15°)
- ✅ Perspective angles (slight rotation)
- ✅ Some photos rotated 90/180° (augmentation handles this)
- ❌ Don't include: Extreme angles (>45°)

#### 3. **Image Quality** (Important)
- ✅ Sharp, high-quality scans
- ✅ Clear phone camera photos
- ✅ Slightly compressed images
- ✅ Minor blur (not extreme)
- ✅ Some pixelation/JPEG artifacts
- ⚠️ Include 10-15% low-quality (but still readable)

#### 4. **Document Conditions** (Reality Check)
- ✅ Brand new documents
- ✅ Slightly worn/creased
- ✅ Laminated vs. non-laminated IDs
- ✅ Different ID card designs (PH has many)
- ✅ Photocopies (common in Philippines)
- ✅ Documents with stamps/signatures

#### 5. **Background Variations**
- ✅ White/plain backgrounds
- ✅ Wooden tables, fabric
- ✅ Cluttered backgrounds (hands, other papers)
- ✅ Outdoor backgrounds (pavement, grass)

#### 6. **Selfie-Specific (for `selfie_with_id` class)**
- ✅ Different skin tones
- ✅ With/without glasses
- ✅ Different facial expressions
- ✅ Indoor/outdoor lighting
- ✅ ID held at different distances
- ✅ Portrait vs. landscape orientation

---

## 📚 Where to Get Training Data

### Option 1: Philippine-Specific Datasets (Most Relevant)

1. **Manual Collection (Best for accuracy)**
   - Ask 10-20 volunteers to submit anonymized docs
   - Use Google Forms + Drive for collection
   - **CRITICAL:** Blur out names, addresses, ID numbers before training!

2. **Philippine Government Open Data**
   - Search for sample document templates
   - Government websites often have sample IDs for reference

### Option 2: International Datasets (Good Starting Point)

1. **Kaggle**
   ```
   https://www.kaggle.com/search?q=id+card+dataset
   https://www.kaggle.com/datasets/datamunge/sign-language-mnist
   https://www.kaggle.com/datasets/trainingdatapro/id-documents-dataset
   ```
   Search terms:
   - "government id dataset"
   - "document classification"
   - "passport id dataset"

2. **Roboflow Universe**
   ```
   https://universe.roboflow.com
   ```
   Search: "ID document", "business card", "document classification"

3. **MIDV-500/2019/2020 (Research Dataset)**
   ```
   https://github.com/fcakyon/midv500
   ```
   50 countries, multiple ID types (includes Asian IDs)

4. **Google Images (Last Resort)**
   - Search "Philippine passport sample"
   - Search "Philippines driver's license template"
   - **IMPORTANT:** Only download public domain/sample images

### Option 3: Synthetic Data Generation

For `proof_of_address`, `business_permit`:
- Use Canva/Figma to create realistic document templates
- Vary fonts, layouts, colors
- Add realistic text (use Lorem Ipsum)
- Print and photograph at different angles/lighting

### Option 4: Web Scraping (Legal Sources Only)

```python
# Example: Scrape public government sample documents
# (Only from sites that allow it)
import requests
from bs4 import BeautifulSoup

# Check robots.txt first!
# Only scrape public sample documents
```

---

## 🚫 Critical: Privacy & Security

### Data Collection Rules

**BEFORE using ANY real documents:**

1. ✅ Get explicit consent from owners
2. ✅ Blur/redact ALL personal information:
   - Names, addresses, ID numbers
   - Signatures, photos (for non-selfie docs)
   - Bank account numbers, amounts
3. ✅ Store training data OUTSIDE git repo
4. ✅ Delete after training (keep only the `.pth` model)

### Recommended Workflow

```bash
# 1. Collect images in a non-git folder
mkdir ~/msme_training_data_temp
cd ~/msme_training_data_temp

# 2. Organize by class
mkdir -p valid_id selfie_with_id business_permit ...

# 3. Copy to project ONLY for training
cp -r ~/msme_training_data_temp/* \
   ~/Capstone_Backend/documents/ml/training_data/

# 4. After training, DELETE originals
rm -rf ~/msme_training_data_temp
rm -rf ~/Capstone_Backend/documents/ml/training_data/*/*.jpg
```

### Gitignore Protection

Your `.gitignore` should have:
```gitignore
# Training data (contains sensitive docs)
documents/ml/training_data/**/*
!documents/ml/training_data/**/README.md

# Trained models (large files)
documents/ml/models/*.pth
documents/ml/models/*.json
```

---

## 🏋️ Training Process

### Prerequisites

```bash
# Install PyTorch (CPU version - good enough for MobileNetV2)
pip install torch torchvision

# For GPU training (optional, much faster)
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# Additional dependencies
pip install pillow opencv-python numpy
```

### Step 1: Verify Dataset

```bash
# Check folder structure
ls -R documents/ml/training_data/

# Count images per class
for dir in documents/ml/training_data/*/; do
  echo "$(basename $dir): $(ls $dir/*.{jpg,jpeg,png} 2>/dev/null | wc -l)"
done
```

Expected output:
```
valid_id: 100
selfie_with_id: 60
business_permit: 80
proof_of_address: 80
business_photo: 60
income_proof: 60
invalid: 120
Total: 560 images
```

### Step 2: Initial Training (Transfer Learning)

```bash
# Default settings (good for 50-100 images per class)
python manage.py train_document_classifier
```

This will:
- ✅ Freeze MobileNetV2 backbone (fast training)
- ✅ Train only classification head
- ✅ Use batch size 32
- ✅ Train for 10 epochs
- ✅ Save best model based on validation accuracy

### Step 3: Check Results

```bash
# Watch training progress
# Expected output:
Epoch 1/10 - Train Loss: 1.2340, Train Acc: 65.23% - Val Loss: 0.9876, Val Acc: 72.50%
Epoch 2/10 - Train Loss: 0.8765, Train Acc: 78.91% - Val Loss: 0.7654, Val Acc: 81.25%
...
Epoch 10/10 - Train Loss: 0.3456, Train Acc: 92.34% - Val Loss: 0.5432, Val Acc: 87.50%
✅ Training complete! Best validation accuracy: 87.50%
```

**Interpretation:**
- **<70% val acc** → Need more data or longer training
- **70-85% val acc** → Good, ready for testing
- **85-95% val acc** → Excellent, production-ready
- **>95% val acc** → Outstanding (or overfitting if train/val gap is large)

### Step 4: Fine-Tuning (If Needed)

If validation accuracy plateaus below 85% and you have 100+ images per class:

```bash
# Unfreeze backbone for full fine-tuning
python manage.py train_document_classifier \
  --epochs 20 \
  --learning-rate 0.0001 \
  --fine-tune
```

**Warning:** Full fine-tuning requires more data to avoid overfitting!

### Step 5: Advanced Hyperparameter Tuning

```bash
# Example: Larger batch size (if you have GPU)
python manage.py train_document_classifier \
  --epochs 15 \
  --batch-size 64 \
  --learning-rate 0.001

# Example: Smaller learning rate for fine-tuning
python manage.py train_document_classifier \
  --epochs 25 \
  --learning-rate 0.00005 \
  --fine-tune
```

---

## 🧪 Testing Your Model

### Test 1: Verify Model Loaded

```bash
python manage.py shell
```

```python
from documents.services.analyzer import get_analyzer

analyzer = get_analyzer()
print(f"Model loaded: {analyzer.model_loaded}")
# Expected: True

# Should show model summary
print(analyzer.model)
```

### Test 2: Classify Sample Image

```python
from documents.services.analyzer import analyze_document

# Test with a real uploaded image
result = analyze_document('/path/to/test_id.jpg', expected_type='valid_id')

print(result)
# Expected output:
{
  'is_valid': True,
  'quality_score': 0.85,
  'quality_issues': [],
  'predicted_type': 'valid_id',
  'type_confidence': 0.92,
  'model_available': True,
  'analysis_mode': 'cnn'
}
```

### Test 3: API Integration Test

```bash
# Upload a test document via API
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@test_id.jpg" \
  -F "document_type=valid_id"

# Check AI analysis in response
# Should include:
{
  "ai_analysis": {
    "predicted_type": "valid_id",
    "type_confidence": 0.92,
    "quality_score": 0.85,
    "analysis_mode": "cnn"
  }
}
```

### Test 4: Confusion Matrix Analysis

Create a test script to check where model fails:

```python
# scripts/test_cnn.py
import os
from pathlib import Path
from documents.services.analyzer import analyze_document
from collections import defaultdict

test_dir = Path('documents/ml/test_data')  # Create this with holdout samples
results = defaultdict(lambda: {'correct': 0, 'wrong': 0})

for class_dir in test_dir.iterdir():
    if not class_dir.is_dir():
        continue
    
    true_label = class_dir.name
    
    for img_path in class_dir.glob('*.jpg'):
        result = analyze_document(str(img_path), expected_type=true_label)
        predicted = result['predicted_type']
        
        if predicted == true_label:
            results[true_label]['correct'] += 1
        else:
            results[true_label]['wrong'] += 1
            print(f"❌ {img_path.name}: Expected {true_label}, got {predicted}")

# Print results
for cls, counts in results.items():
    total = counts['correct'] + counts['wrong']
    accuracy = (counts['correct'] / total * 100) if total > 0 else 0
    print(f"{cls}: {accuracy:.1f}% ({counts['correct']}/{total})")
```

---

## 📈 Improving Model Performance

### If Validation Accuracy is Low (<75%)

**Possible causes:**

1. **Insufficient data**
   ```bash
   # Check sample counts
   for dir in documents/ml/training_data/*/; do
     count=$(ls $dir/*.{jpg,jpeg,png} 2>/dev/null | wc -l)
     echo "$(basename $dir): $count"
     if [ $count -lt 50 ]; then
       echo "  ⚠️ Too few samples!"
     fi
   done
   ```
   **Solution:** Collect 50+ images per class

2. **Class imbalance**
   ```
   valid_id: 200 images
   income_proof: 20 images  ← Problem!
   ```
   **Solution:** Balance classes (each should have similar counts)

3. **Poor image quality**
   **Solution:** Remove completely blurry/dark images

4. **Training too short**
   ```bash
   # Try more epochs
   python manage.py train_document_classifier --epochs 20
   ```

### If Train Accuracy >> Val Accuracy (Overfitting)

Example: Train 95%, Val 70% (gap >20%)

**Solutions:**

1. **Add more training data** (best solution)

2. **Increase data augmentation** (edit training script):
   ```python
   # In train_document_classifier.py, increase augmentation:
   transforms.RandomRotation(15),  # Was 10
   transforms.ColorJitter(brightness=0.3, contrast=0.3),  # Was 0.2
   ```

3. **Add dropout** (edit cnn_model.py):
   ```python
   nn.Dropout(p=0.4),  # Increase from 0.2/0.3
   ```

4. **Reduce training epochs**:
   ```bash
   python manage.py train_document_classifier --epochs 8
   ```

### If Model is Slow to Train

1. **Use GPU** (if available):
   ```bash
   # Check GPU availability
   python -c "import torch; print(torch.cuda.is_available())"
   ```

2. **Reduce batch size**:
   ```bash
   python manage.py train_document_classifier --batch-size 16
   ```

3. **Use CPU-optimized PyTorch**:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   ```

---

## 🎯 Production Deployment Checklist

Before deploying trained model:

- [ ] Validation accuracy ≥ 85%
- [ ] Tested on 20+ real-world images not in training set
- [ ] Confusion matrix shows no critical failures
- [ ] Model file size reasonable (<50MB)
- [ ] API integration tested
- [ ] All training data deleted from production server
- [ ] Model files added to `.gitignore`
- [ ] Fallback to quality-check mode works if model fails

---

## 📊 Expected Model Performance

### File Sizes
- `document_classifier.pth`: ~15-20MB (MobileNetV2 is lightweight)
- `model_config.json`: <1KB

### Inference Speed
- **CPU:** ~100-200ms per image
- **GPU:** ~10-30ms per image

### Memory Usage
- **Model in RAM:** ~50MB
- **Per inference:** ~10MB temporary

---

## 🔄 Retraining Strategy

### When to Retrain

1. **User feedback indicates errors** (track misclassifications)
2. **New document types added** (e.g., new PH ID format)
3. **After collecting 100+ new images**
4. **Every 6 months** (documents evolve)

### Incremental Training

```bash
# Add new images to existing training_data folders
cp new_images/* documents/ml/training_data/valid_id/

# Retrain from scratch (recommended)
python manage.py train_document_classifier --epochs 15

# Or continue from previous model (advanced)
# Requires code modification to load previous weights
```

---

## 🐛 Troubleshooting

### Error: "PyTorch not installed"
```bash
pip install torch torchvision pillow opencv-python
```

### Error: "Training data folder not found"
```bash
# Check folder exists
ls documents/ml/training_data/
# Should show 7 folders
```

### Error: "Only X training samples found"
- You need at least 50 images total across all classes
- Add more images to each folder

### Error: "CUDA out of memory"
```bash
# Reduce batch size
python manage.py train_document_classifier --batch-size 8
```

### Warning: "Model not loading in production"
- Check `documents/ml/models/document_classifier.pth` exists
- Check file permissions (should be readable by Django user)
- Check logs: `tail -f logs/documents.log`

---

## 📚 Additional Resources

### Transfer Learning
- https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html

### Data Augmentation
- https://pytorch.org/vision/stable/transforms.html

### MobileNetV2 Paper
- https://arxiv.org/abs/1801.04381

### Document Classification Research
- https://paperswithcode.com/task/document-image-classification

---

## ✅ Quick Start Summary

```bash
# 1. Collect 50+ images per class (280+ total)
# 2. Place in documents/ml/training_data/<class_name>/
# 3. Install dependencies
pip install torch torchvision pillow opencv-python

# 4. Train model
python manage.py train_document_classifier

# 5. Check results (should see 85-95% val accuracy)

# 6. Test via API
# Upload document → check ai_analysis field

# 7. If accuracy <85%, collect more data and retrain
```

**Target:** 85-95% validation accuracy = Production-ready! 🎉

---

## Section 6: CNN_MODEL_IMPROVEMENTS.md

# CNN Model Improvements Playbook

> **Companion to:** [CNN Final Guide](#section-2-cnn_final_guidemd)
> Use this playbook to systematically raise accuracy and reliability of the MobileNetV2 document classifier.

---

## ⚡ Prioritized Checklist — Do These First for Fastest Accuracy Gains

> Work top-to-bottom. Each item is ordered by **expected impact per hour invested**.

- [ ] **1. Balance class counts** — ensure no class has < 40 images and the largest:smallest ratio is ≤ 2:1
- [ ] **2. Add more data to the weakest class** — identify it via confusion matrix; add 30–50 images
- [ ] **3. Remove corrupt / mislabeled images** — run `check_training_data.py`, visually audit 10 random images per class
- [ ] **4. Increase augmentation strength** — raise rotation to ±15°, color jitter to ±30 %
- [ ] **5. Train with more epochs** — try `--epochs 20` instead of default 10
- [ ] **6. Enable fine-tuning** — unfreeze backbone if you have 100+ images / class (`--fine-tune`)
- [ ] **7. Add dropout** — set `Dropout(0.4)` if overfitting persists
- [ ] **8. Calibrate confidence threshold** — pick a threshold so that predictions below it fall back to manual review
- [ ] **9. Collect more real-world test images** — validate on 20+ never-seen images
- [ ] **10. Set up periodic retraining** — retrain every 6 months or after 100+ new images

---

## 1 · Data Improvements

### 1.1 Labeling Rules

| Rule | Why |
|------|-----|
| One class per image — no multi-label | MobileNetV2 head uses softmax (single-class output) |
| Label by the **primary document visible**, not background objects | Prevents noisy decision boundaries |
| When in doubt, label as `invalid` | False negatives are safer than false positives in loan processing |
| Use a second reviewer for ambiguous images | Inter-annotator disagreement highlights genuinely hard cases |

**Labeling process:**

1. Place image in the folder matching its document type.
2. If a photo contains two overlapping documents, crop to the dominant one.
3. Mark borderline images with a `__review` suffix (e.g., `img042__review.jpg`) and decide as a team.

### 1.2 Data Cleaning

| Step | Command / Action |
|------|-----------------|
| Find corrupt files | `python scripts/check_training_data.py` — flags 0-byte and unreadable files |
| Remove duplicates | Use `fdupes -r documents/ml/training_data/` (install via `brew install fdupes`) |
| Delete extreme outliers | Manually remove images that are pitch-black, completely white, or upside-down screenshots |
| Verify class folder names | Must exactly match: `valid_id`, `selfie_with_id`, `business_permit`, `proof_of_address`, `business_photo`, `income_proof`, `invalid` |

### 1.3 Augmentation Strategy

The training script already applies:

| Transform | Current Setting |
|-----------|----------------|
| Random horizontal flip | 50 % probability |
| Random rotation | ±10° |
| Random resized crop | 256 → 224 |
| Color jitter | brightness ±20 %, contrast ±20 % |

**Recommended upgrades for small datasets (< 100 / class):**

```python
# In train_document_classifier.py transforms
transforms.RandomRotation(15),                       # ±10° → ±15°
transforms.ColorJitter(
    brightness=0.3, contrast=0.3,                    # 0.2 → 0.3
    saturation=0.2, hue=0.05                         # add saturation + hue
),
transforms.RandomAffine(degrees=0, translate=(0.05, 0.05)),  # small shifts
transforms.RandomPerspective(distortion_scale=0.1, p=0.3),   # slight perspective
transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),    # simulate phone blur
```

> **Caution:** Don't over-augment. If training accuracy drops below 60 %, ease back.

**Per-class augmentation:** If one class has far fewer images, apply *extra* augmentation only to that class (e.g., duplicate `income_proof` images with heavier transforms) so every class contributes equally to each epoch.

---

## 2 · Model Improvements

### 2.1 Architecture Choices

| Option | When to Use | Pros | Cons |
|--------|-------------|------|------|
| **MobileNetV2 (current)** | Default — small dataset, CPU deployment | Lightweight (~15 MB), fast inference | Lower capacity than larger models |
| **EfficientNet-B0** | 500+ images, need more accuracy | Better accuracy/param ratio | Slightly larger (~20 MB) |
| **ResNet-18** | Need a well-studied baseline | Extensive research support | Heavier than MobileNet (~45 MB) |
| **EfficientNet-B3** | 1 000+ images, GPU available | Highest accuracy ceiling | Larger (~50 MB), slower CPU inference |

> **Recommendation:** Stick with MobileNetV2 until you exhaust data improvements. Architecture upgrades give diminishing returns compared to more data at small dataset sizes.

### 2.2 Transfer Learning

Transfer learning is **already enabled** — MobileNetV2 loads ImageNet weights and freezes the backbone.

**Stages:**

| Stage | Backbone | Classifier Head | When |
|-------|----------|-----------------|------|
| **Stage 1 — Feature extraction** | Frozen | Training | < 100 images / class |
| **Stage 2 — Fine-tuning (last 3 blocks)** | Partially unfrozen | Training | 100–200 images / class |
| **Stage 3 — Full fine-tuning** | All unfrozen | Training | 200+ images / class |

**How to enable Stage 2 (partial fine-tuning):**

```python
# Unfreeze last 3 MobileNetV2 blocks
for param in model.features[-3:].parameters():
    param.requires_grad = True
```

### 2.3 Fine-Tuning Tips

- Use a **10× smaller learning rate** for the backbone than the classifier head (differential LR).
- **Warm up** for 1–2 epochs with the backbone frozen, then unfreeze.
- Watch the train/val gap — if it grows, re-freeze or add regularization.

---

## 3 · Training Improvements

### 3.1 Hyperparameters

| Parameter | Default | Tuning Range | Notes |
|-----------|---------|-------------|-------|
| **Learning rate** | 0.001 | 0.0001 – 0.01 | Reduce for fine-tuning |
| **Batch size** | 32 | 8 – 64 | Limited by GPU RAM; 16 is safe for CPU |
| **Epochs** | 10 | 8 – 30 | More epochs if data is large; less if small |
| **Optimizer** | Adam | Adam / AdamW / SGD+momentum | AdamW adds weight-decay regularization |
| **Weight decay** | 0 | 1e-4 – 1e-2 | Helps prevent overfitting |
| **LR scheduler** | StepLR | CosineAnnealing / ReduceOnPlateau | CosineAnnealing is generally better |

### 3.2 Regularization

| Technique | Implementation | Effect |
|-----------|---------------|--------|
| **Dropout** | `nn.Dropout(0.3–0.5)` before final FC layer | Prevents co-adaptation of neurons |
| **Weight decay** | `optimizer = AdamW(params, lr, weight_decay=1e-4)` | L2 penalty on large weights |
| **Label smoothing** | `CrossEntropyLoss(label_smoothing=0.1)` | Softens overconfident predictions |
| **Data augmentation** | See §1.3 above | Generates virtual training examples |
| **Early stopping** | Already built in (saves best val-acc checkpoint) | Stops before overfitting |

### 3.3 Early Stopping

The training script already saves the best model by validation accuracy. Additionally:

- If val loss does not improve for **5 consecutive epochs**, consider stopping manually.
- The saved checkpoint is the best one, so extra epochs past the peak don't hurt the final model—but they waste time.

---

## 4 · Evaluation Improvements

### 4.1 Metrics to Track

| Metric | What It Tells You | How to Compute |
|--------|-------------------|----------------|
| **Overall accuracy** | % of all images classified correctly | Simple ratio |
| **Per-class accuracy (recall)** | How well each class is detected | Confusion matrix diagonal |
| **Precision** | Of images predicted as class X, how many actually are X | TP / (TP + FP) |
| **F1 score** | Harmonic mean of precision and recall | 2 × P × R / (P + R) |
| **Confidence histogram** | Distribution of model confidence scores | Plot `type_confidence` values |
| **AUC-ROC** | Overall ranking quality (threshold-independent) | `sklearn.metrics.roc_auc_score` |

### 4.2 Confusion Matrix

Run on the holdout test set:

```bash
python scripts/test_cnn_model.py documents/ml/test_data/ --confusion
```

**What to look for:**

- **Off-diagonal hot spots** = classes the model confuses (e.g., `business_permit` ↔ `proof_of_address`).
- **Row with many errors** = that class needs more / better data.
- **Column with many false positives** = the model over-predicts that class.

### 4.3 Error Buckets

After running the confusion matrix, group errors into actionable categories:

| Bucket | Example | Action |
|--------|---------|--------|
| **Labeling error** | Image was mislabeled by collector | Fix the label |
| **Low quality** | Extremely blurry or dark photo | Add to `invalid` or remove from training |
| **Class ambiguity** | Barangay clearance with both business + address info | Decide canonical label; add more examples of each |
| **Rare variant** | New ID card design not in training set | Collect more samples of that variant |
| **Augmentation gap** | All errors are rotated / dark images | Increase rotation / brightness augmentation |

---

## 5 · Deployment Considerations

### 5.1 Confidence Thresholding

Not all predictions should be trusted equally. Set a **confidence threshold** so that low-confidence predictions are flagged for manual review.

| Strategy | Threshold | Effect |
|----------|-----------|--------|
| **Conservative** | `type_confidence ≥ 0.90` | Fewer auto-classifications, but almost all are correct |
| **Balanced** | `type_confidence ≥ 0.75` | More auto-classifications with reasonable accuracy |
| **Permissive** | `type_confidence ≥ 0.50` | Most images auto-classified; higher error rate |

> **Recommendation:** Start with **0.80** and adjust based on loan-officer feedback.

**Implementation:**

```python
if result['type_confidence'] >= THRESHOLD:
    # Auto-classify
    document.ai_verified = True
else:
    # Flag for manual review
    document.ai_verified = False
    document.needs_review = True
```

### 5.2 Confidence Calibration

Raw softmax outputs are often **overconfident**. To calibrate:

1. **Temperature scaling** — divide logits by a scalar *T* > 1 before softmax. Tune *T* on the validation set to minimize negative log-likelihood.
2. **Reliability diagram** — plot predicted confidence vs. actual accuracy in bins. A well-calibrated model follows the diagonal.
3. **Expected Calibration Error (ECE)** — single number summarizing miscalibration. Aim for ECE < 0.05.

### 5.3 Model Versioning

- Name model files with a date or version: `document_classifier_v2_20260217.pth`
- Keep the previous version as a rollback: `document_classifier_v1.pth.bak`
- Log which model version is active in `model_config.json`.

### 5.4 Monitoring in Production

| What to Monitor | How |
|----------------|-----|
| Average confidence per day | Log `type_confidence` to your analytics dashboard |
| Rejection rate (below threshold) | Track % of images flagged for manual review |
| Per-class distribution | Detect data drift (e.g., sudden spike in `invalid`) |
| Inference latency | Ensure < 200 ms P95 on CPU |

---

## 6 · Quick Reference — Improvement Decision Tree

```
Accuracy too low?
│
├── < 70 % ──► Need more data (at least 50 / class)
│
├── 70–80 % ──► Check class balance → add data to weak classes
│               └─► Try --epochs 15–20
│
├── 80–85 % ──► Enable fine-tuning (--fine-tune) if 100+ / class
│               └─► Increase augmentation strength
│
├── 85–90 % ──► Partial fine-tuning (last 3 blocks)
│               └─► Add label smoothing (0.1)
│               └─► Calibrate confidence threshold
│
└── 90 %+ ──► Diminishing returns from model changes
              └─► Focus on error buckets + real-world edge cases
              └─► Add confidence calibration (temperature scaling)
```

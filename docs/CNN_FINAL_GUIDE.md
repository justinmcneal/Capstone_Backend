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

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

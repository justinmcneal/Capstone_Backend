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

📚 **[Complete CNN Training Guide](CNN_TRAINING_GUIDE.md)** - Everything you need to know  
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
   - [CNN_TRAINING_GUIDE.md](CNN_TRAINING_GUIDE.md) - Comprehensive training documentation

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

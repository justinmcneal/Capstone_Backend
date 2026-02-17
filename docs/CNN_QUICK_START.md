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
- [CNN_TRAINING_GUIDE.md](CNN_TRAINING_GUIDE.md) - Complete training guide
- [DATA_COLLECTION_CHECKLIST.md](../documents/ml/training_data/DATA_COLLECTION_CHECKLIST.md) - Detailed checklist
- [CNN_DOCUMENT_ANALYSIS.md](CNN_DOCUMENT_ANALYSIS.md) - API integration guide

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

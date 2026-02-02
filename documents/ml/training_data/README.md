# CNN Training Data - Philippine MSME Documents

> **Project:** MSME Pathways - Document Classification  
> **Model:** MobileNetV2 (Transfer Learning)  
> **Target Accuracy:** >85%

---

## 📁 Folder Structure

```
training_data/
├── valid_id/           # 50-100 images (PhilSys, Driver's License, UMID, etc.)
├── selfie_with_id/     # 30-50 images (Person holding ID)
├── business_permit/    # 30-50 images (DTI, Mayor's Permit, Barangay Permit)
├── proof_of_address/   # 30-50 images (Meralco, Water bill, Barangay Cert)
├── business_photo/     # 30-50 images (Sari-sari store, market stall)
├── income_proof/       # 30-50 images (Bank statement, GCash, receipts)
└── invalid/            # 50-100 images (Random photos, blurry docs, memes)
```

**Total Target: 270-500 images minimum**

---

## 📊 Collection Progress

| Category | Target | Current | Status |
|----------|--------|---------|--------|
| valid_id | 50-100 | 0 | ⬜ Not started |
| selfie_with_id | 30-50 | 0 | ⬜ Not started |
| business_permit | 30-50 | 0 | ⬜ Not started |
| proof_of_address | 30-50 | 0 | ⬜ Not started |
| business_photo | 30-50 | 0 | ⬜ Not started |
| income_proof | 30-50 | 0 | ⬜ Not started |
| invalid | 50-100 | 0 | ⬜ Not started |

**Update this table as you add images!**

---

## 🔗 Quick Download Links

### For valid_id
| Source | URL | Notes |
|--------|-----|-------|
| MIDV-500 | https://github.com/fcakyon/midv500 | 500 ID documents |
| Kaggle IDs | https://www.kaggle.com/datasets/trainingdatapro/identity-document-image-dataset | Identity documents |
| Roboflow | https://universe.roboflow.com/search?q=id+card | ID card datasets |

### For business_permit, proof_of_address
| Search Term | Where |
|-------------|-------|
| "DTI certificate sample Philippines" | Google Images |
| "Mayor's permit sample Philippines" | Google Images |
| "Barangay certificate sample" | Google Images |
| "Meralco bill sample" | Google Images |
| "Manila Water bill sample" | Google Images |

### For business_photo (Easiest!)
| Method | How |
|--------|-----|
| Walk around | Take photos of local sari-sari stores, tiangge |
| Google Images | Search "sari-sari store Philippines" |
| Google Maps | Street view of local businesses |

### For invalid (Super Easy!)
| Source | What |
|--------|------|
| Your phone | Random photos from gallery |
| Internet | Memes, random images |
| Take photos | Intentionally blurry documents |

---

## ⚡ Quick Start Commands

### Check your image counts:
```bash
# Count images in each folder
find . -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" | wc -l

# Count per folder
for dir in */; do echo "$dir: $(find "$dir" -name "*.jpg" -o -name "*.jpeg" -o -name "*.png" | wc -l)"; done
```

### After collecting images, train the model:
```bash
python manage.py train_document_classifier --epochs 20
```

---

## 📋 Image Requirements

| Requirement | Specification |
|-------------|---------------|
| **Format** | JPG, JPEG, or PNG |
| **Minimum Size** | 224 x 224 pixels |
| **Naming** | Any filename (e.g., `id_001.jpg`) |
| **Quality** | Clear and readable |

---

## ⚠️ Security Notes

1. **DO NOT commit real personal documents**
2. Use sample/template documents when possible
3. Blur sensitive information (account numbers, TIN)
4. Training images are gitignored (only READMEs committed)

---

## 📖 Category Details

See the README.md in each folder for:
- Specific examples of what to collect
- Where to find images
- Tips for that category

---

## ✅ Ready to Train?

When you have at least 30 images per category:

```bash
# Navigate to project root
cd /Users/gab/Documents/GitHub/Capstone_Backend

# Run training (10 epochs default)
python manage.py train_document_classifier

# Or with more epochs for better accuracy
python manage.py train_document_classifier --epochs 20
```

Output will be saved to:
- `documents/ml/models/document_classifier.pth`
- `documents/ml/models/model_config.json`

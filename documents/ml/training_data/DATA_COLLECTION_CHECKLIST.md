# CNN Training Data Collection Checklist

> **Goal:** Collect 560+ high-quality, diverse images for document classification

---

## 📋 Collection Progress Tracker

### Target Quantities

| Class | Target | Current | Status | Notes |
|-------|--------|---------|--------|-------|
| valid_id | 100 | 0 | ⬜️ Not started | Philippine IDs (passport, driver's license, UMID, etc.) |
| selfie_with_id | 60 | 0 | ⬜️ Not started | Person holding any valid ID |
| business_permit | 80 | 0 | ⬜️ Not started | DTI, SEC, Mayor's permit |
| proof_of_address | 80 | 0 | ⬜️ Not started | Utility bills, barangay cert |
| business_photo | 60 | 0 | ⬜️ Not started | Storefront, sari-sari store photos |
| income_proof | 60 | 0 | ⬜️ Not started | Bank statements, receipts (optional for borrowers) |
| invalid | 120 | 0 | ⬜️ Not started | Random images (animals, landscapes, text, blurry docs) |
| **TOTAL** | **560** | **0** | ⬜️ | - |

---

## 📸 Image Quality Checklist

For EACH class, ensure you have:

### ✅ Lighting Variations (20% each)
- [ ] 20% bright daylight
- [ ] 20% indoor lighting (yellow/warm)
- [ ] 20% indoor lighting (white/cool)
- [ ] 20% flash photography
- [ ] 20% slightly dark (but readable)

### ✅ Angle Variations
- [ ] 60% straight-on shots (ideal)
- [ ] 20% slight tilt (5-10°)
- [ ] 10% moderate tilt (10-15°)
- [ ] 10% perspective angle (document slightly rotated)

### ✅ Quality Variations
- [ ] 40% high-quality (sharp, clear)
- [ ] 40% medium-quality (normal phone camera)
- [ ] 15% slightly compressed/pixelated
- [ ] 5% slightly blurry (but still readable)

### ✅ Background Variations
- [ ] 30% plain white background
- [ ] 25% wooden table/desk
- [ ] 20% fabric background (bed, couch)
- [ ] 15% cluttered background (papers, hands)
- [ ] 10% outdoor background (pavement, grass)

### ✅ Document Conditions
- [ ] 60% brand new/pristine documents
- [ ] 25% slightly worn/creased
- [ ] 10% laminated (for IDs)
- [ ] 5% photocopies (common in Philippines)

---

## 🇵🇭 Philippine-Specific Requirements

### For `valid_id` folder (100 images)

**Required ID types** (aim for diversity):
- [ ] 20 images: Philippine Passport
- [ ] 20 images: Driver's License (LTO)
- [ ] 15 images: UMID (Unified Multi-Purpose ID)
- [ ] 15 images: SSS ID
- [ ] 10 images: Postal ID
- [ ] 10 images: PRC ID (Professional Regulation Commission)
- [ ] 5 images: Voter's ID (COMELEC)
- [ ] 5 images: PhilHealth ID

**Variations to include:**
- [ ] Old vs. new format IDs (PH IDs change design)
- [ ] With/without signature line visible
- [ ] Front and back of ID (count as 2 images)
- [ ] Plastic card vs. paper ID

### For `selfie_with_id` folder (60 images)

**Diversity requirements:**
- [ ] 30 images: Male subjects
- [ ] 30 images: Female subjects
- [ ] Various ages (20-60 years old)
- [ ] With/without glasses (30/30 split)
- [ ] Different skin tones (Filipino diversity)
- [ ] Indoor/outdoor lighting (40/20 split)
- [ ] ID held at different distances (close/far)

**Pose variations:**
- [ ] 40 images: ID held at chest level
- [ ] 10 images: ID held near face
- [ ] 10 images: ID held at arm's length

### For `business_permit` folder (80 images)

**Philippine permit types:**
- [ ] 30 images: DTI Business Registration
- [ ] 25 images: Mayor's Permit (different cities)
- [ ] 15 images: SEC Certificate (for corporations)
- [ ] 10 images: Barangay Clearance with business info

**Variations:**
- [ ] Different years (2020-2024)
- [ ] Different municipalities (Manila, Quezon City, Cebu, etc.)
- [ ] With/without stamps
- [ ] Original vs. photocopies

### For `proof_of_address` folder (80 images)

**Document types:**
- [ ] 30 images: Electricity bills (Meralco, local coops)
- [ ] 20 images: Water bills
- [ ] 15 images: Barangay Certificate of Residency
- [ ] 10 images: Internet/cable bills (PLDT, Converge, Sky)
- [ ] 5 images: Bank statements with address

**Requirements:**
- [ ] Recent documents (within 3 months)
- [ ] Clear address visible
- [ ] Different bill formats/companies

### For `business_photo` folder (60 images)

**Types of businesses:**
- [ ] 20 images: Sari-sari stores
- [ ] 15 images: Small retail shops
- [ ] 10 images: Food stalls/carinderias
- [ ] 10 images: Service businesses (parlor, repair shop)
- [ ] 5 images: Home-based businesses

**Photo characteristics:**
- [ ] 40 images: Storefront with signage visible
- [ ] 10 images: Interior of business
- [ ] 10 images: Product inventory photos

### For `income_proof` folder (60 images)

**Document types:**
- [ ] 25 images: Bank statements (various banks)
- [ ] 20 images: Sales receipts/invoices
- [ ] 10 images: Remittance receipts
- [ ] 5 images: ITR (Income Tax Return)

**Note:** This class is OPTIONAL for informal MSMEs, so diversity is key.

### For `invalid` folder (120 images)

**Critical for model accuracy!** Include:

- [ ] 30 images: Random photos (landscapes, animals, food)
- [ ] 20 images: Completely blurry documents (unreadable)
- [ ] 20 images: Screenshots of documents (not photos)
- [ ] 15 images: Text-only pages (contracts, agreements)
- [ ] 15 images: Foreign IDs (not Philippine)
- [ ] 10 images: Damaged/torn documents
- [ ] 10 images: Blank paper/background-only images

**Why:** Model needs to learn what is NOT a valid document!

---

## 🔒 Privacy & Anonymization Checklist

**BEFORE adding ANY image to training data:**

### For IDs and Documents:
- [ ] Blur/redact full names
- [ ] Blur/redact ID numbers
- [ ] Blur/redact addresses
- [ ] Blur/redact signatures
- [ ] Blur/redact birthdays (partially OK)
- [ ] Keep only document structure/layout visible

### For Selfies:
- [ ] Get explicit consent from subject
- [ ] Consider face blurring (but keep "person holding ID" context)
- [ ] Blur ID details in the photo

### Recommended Tools:
```bash
# Python script for bulk blurring
pip install pillow opencv-python

# Use GIMP/Photoshop for manual redaction
# Or online tools: photopea.com, cleanup.pictures
```

### Sample Anonymization Script:
```python
# scripts/anonymize_images.py
import cv2
import numpy as np
from pathlib import Path

def blur_region(image_path, x, y, width, height):
    """Blur a rectangular region in an image"""
    img = cv2.imread(str(image_path))
    
    # Extract region
    roi = img[y:y+height, x:x+width]
    
    # Apply strong blur
    blurred = cv2.GaussianBlur(roi, (99, 99), 30)
    
    # Replace region
    img[y:y+height, x:x+width] = blurred
    
    # Save
    cv2.imwrite(str(image_path), img)
    print(f"✓ Blurred {image_path.name}")

# Usage:
# blur_region('id_001.jpg', x=100, y=50, width=300, height=50)  # Name area
# blur_region('id_001.jpg', x=100, y=150, width=300, height=50)  # ID number
```

---

## 📥 Data Source Checklist

### ✅ Legal & Ethical Sources

- [ ] **Volunteers** (10-20 people, get consent forms)
- [ ] **Public datasets** (Kaggle, Roboflow - check licenses)
- [ ] **Government sample templates** (official website samples)
- [ ] **Stock photo sites** (Unsplash, Pexels with commercial license)
- [ ] **Synthetic generation** (create fake documents with templates)

### ❌ ILLEGAL Sources (DO NOT USE)

- [ ] ❌ Leaked/stolen ID databases
- [ ] ❌ Facebook/social media scraped images (privacy violation)
- [ ] ❌ Google Images (many are copyrighted)
- [ ] ❌ Customer data from other systems (GDPR/privacy violation)

---

## 🛠️ Collection Workflow

### Step 1: Setup Collection Folder
```bash
mkdir -p ~/msme_cnn_data_temp/{valid_id,selfie_with_id,business_permit,proof_of_address,business_photo,income_proof,invalid}
```

### Step 2: Download from Sources
```bash
# Example: Kaggle dataset
kaggle datasets download -d <dataset-name>
unzip <dataset-name>.zip -d ~/msme_cnn_data_temp/valid_id/
```

### Step 3: Anonymize Images
```bash
# Run anonymization script on all images
python scripts/anonymize_images.py ~/msme_cnn_data_temp/
```

### Step 4: Verify Counts
```bash
for dir in ~/msme_cnn_data_temp/*/; do
  count=$(ls $dir/*.{jpg,jpeg,png} 2>/dev/null | wc -l)
  echo "$(basename $dir): $count"
done
```

### Step 5: Move to Training Folder
```bash
# ONLY after anonymization!
cp -r ~/msme_cnn_data_temp/* \
   ~/Documents/GitHub/Capstone_Backend/documents/ml/training_data/
```

### Step 6: Clean Up
```bash
# AFTER successful training, delete originals
rm -rf ~/msme_cnn_data_temp
```

---

## 📊 Pre-Training Validation

Before running `train_document_classifier`, verify:

### File Format Check
```bash
# Should only show JPEG/PNG
find documents/ml/training_data/ -type f | grep -E '\.(jpg|jpeg|png)$' | wc -l

# Check for PDFs (CNN can't process these)
find documents/ml/training_data/ -name "*.pdf" | wc -l
# Should be 0
```

### Image Dimensions Check
```python
# scripts/check_dimensions.py
from PIL import Image
from pathlib import Path

min_size = 224
issues = []

for img_path in Path('documents/ml/training_data').rglob('*.jpg'):
    img = Image.open(img_path)
    if img.size[0] < min_size or img.size[1] < min_size:
        issues.append(f"{img_path.name}: {img.size}")

if issues:
    print(f"⚠️ {len(issues)} images too small:")
    for issue in issues:
        print(f"  {issue}")
else:
    print("✅ All images meet size requirements")
```

### File Corruption Check
```python
# scripts/check_corruption.py
from PIL import Image
from pathlib import Path

corrupted = []

for img_path in Path('documents/ml/training_data').rglob('*.jpg'):
    try:
        img = Image.open(img_path)
        img.verify()  # Check if valid
    except Exception as e:
        corrupted.append(str(img_path))

if corrupted:
    print(f"❌ {len(corrupted)} corrupted images found")
    for path in corrupted:
        print(f"  Delete: {path}")
else:
    print("✅ No corrupted images found")
```

---

## 🎯 Quality Targets

### Minimum Viable Dataset (MVP)
- **Total:** 280 images (40 per class)
- **Expected accuracy:** 75-85%
- **Time to collect:** 2-3 days

### Recommended Dataset
- **Total:** 560 images (80 per class)
- **Expected accuracy:** 85-92%
- **Time to collect:** 1 week

### Excellent Dataset
- **Total:** 1000+ images (140+ per class)
- **Expected accuracy:** 92-96%
- **Time to collect:** 2-3 weeks

---

## 📞 Volunteer Collection Template

### Google Form Questions

```
Consent Form for Training Data Collection

1. I consent to providing sample documents for MSME Pathways CNN training
   [ ] Yes, I consent

2. Please upload a photo of a valid Philippine ID (we will blur personal info)
   [File Upload]

3. Please upload a selfie holding your ID
   [File Upload]

4. (Optional) Business permit or DTI registration
   [File Upload]

5. (Optional) Proof of address (utility bill, barangay cert)
   [File Upload]

6. I understand all personal information will be anonymized/deleted after training
   [ ] Yes, I understand
```

### Email Template

```
Subject: Help Train MSME Pathways AI - Volunteer Document Collection

Hi [Name],

I'm building an AI system to help MSMEs access loans in the Philippines. 

To train the document verification AI, I need sample photos of common documents 
(IDs, business permits, etc.). All personal information will be completely 
blurred/removed, and images will be deleted after training.

Can you help by submitting 2-3 document photos?

📋 Form: [Google Form Link]
⏱️ Time: 5 minutes
🔒 Privacy: All info anonymized

Thank you!
[Your Name]
```

---

## ✅ Final Checklist Before Training

- [ ] All 7 folders have images
- [ ] Each folder has 40+ images (280+ total)
- [ ] All images are JPEG/PNG (no PDFs)
- [ ] All images are at least 224x224 pixels
- [ ] No corrupted images (run check script)
- [ ] All personal information blurred/redacted
- [ ] Diversity requirements met (lighting, angles, quality)
- [ ] Philippine-specific document types included
- [ ] `invalid` folder has 100+ negative samples
- [ ] Training data folder is in `.gitignore`
- [ ] Original unprocessed images backed up elsewhere

**When all checked:** Run `python manage.py train_document_classifier` 🚀

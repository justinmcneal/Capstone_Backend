# Document Analysis ML - Training Data

This folder contains training data for the document classification CNN model.

## Folder Structure

```
training_data/
├── valid_id/           # Government IDs (driver's license, passport, etc.)
├── selfie_with_id/     # Selfie holding ID
├── business_permit/    # DTI/SEC/Mayor's permits
├── proof_of_address/   # Utility bills, barangay certificates
├── business_photo/     # Photos of business premises
├── income_proof/       # Bank statements, sales records
└── invalid/            # Random images, blurry docs (negative samples)
```

## How to Collect Training Data

### Option 1: Public Datasets (Recommended to start)

1. **Kaggle Datasets:**
   - Search "ID card dataset" on kaggle.com
   - https://www.kaggle.com/datasets (search "document classification")
   - Download and place in appropriate folders

2. **Roboflow:**
   - https://universe.roboflow.com (search "ID document")
   - Free datasets available for research

3. **MIDV-500:**
   - Public dataset of ID documents
   - https://github.com/fcakyon/midv500

### Option 2: Generate Synthetic Data

You can use document templates to generate training samples.

### Option 3: Collect Real Samples

1. Ask testers to submit sample documents
2. Anonymize/blur sensitive information
3. Aim for 50-100 images per category

## Recommended Quantities

| Category | Minimum | Recommended |
|----------|---------|-------------|
| valid_id | 50 | 100+ |
| selfie_with_id | 30 | 50+ |
| business_permit | 30 | 50+ |
| proof_of_address | 30 | 50+ |
| business_photo | 30 | 50+ |
| income_proof | 30 | 50+ |
| invalid | 50 | 100+ |

## Image Requirements

- **Format:** JPEG or PNG
- **Size:** At least 224x224 pixels (will be resized)
- **Quality:** Clear, readable images
- **Naming:** Any filename is fine (e.g., `id_001.jpg`, `permit_sample.png`)

## After Collecting Data

Run the training script:
```bash
python manage.py train_document_classifier
```

## Security Note

⚠️ **Do NOT commit real personal documents to version control.**

Add to `.gitignore`:
```
documents/ml/training_data/
!documents/ml/training_data/README.md
```

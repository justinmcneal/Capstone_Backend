# AI Implementation Plan - CNN + NLP

> **Author:** System Developer (Eli Gabriel Soriano)  
> **Created:** February 2, 2026  
> **Project:** MSME Pathways - Smart Loan Support for the Informal Sector

---

## Executive Summary

This document outlines the implementation plan for the AI components of MSME Pathways:

| Component | Technology | Status | Priority |
|-----------|------------|--------|----------|
| **CNN Document Classifier** | MobileNetV2 (PyTorch) | ⚠️ Architecture ready, needs training | 🔴 High |
| **NLP Chatbot** | Groq API (LLaMA 3.1) | ✅ Implemented | 🟡 Enhancement |
| **CNN + NLP Integration** | Custom | ❌ Not started | 🟢 After CNN |

---

## Current Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Django Backend                               │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   documents/                                ││
│  │  ├── services/                                              ││
│  │  │   ├── cnn_model.py      ✅ MobileNetV2 classifier        ││
│  │  │   └── analyzer.py       ✅ Quality check + CNN inference ││
│  │  ├── ml/                                                    ││
│  │  │   ├── models/           ⚠️ Empty (needs .pth file)       ││
│  │  │   └── training_data/    ⚠️ Empty (needs images)          ││
│  │  └── management/commands/                                   ││
│  │       └── train_document_classifier.py  ✅ Ready to run     ││
│  └─────────────────────────────────────────────────────────────┘│
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                   ai_assistant/                             ││
│  │  ├── services/                                              ││
│  │  │   └── llm_service.py    ✅ Groq API integration          ││
│  │  ├── views/                                                 ││
│  │  │   └── chat_views.py     ✅ Chat endpoints                ││
│  │  └── models/                                                ││
│  │       └── interaction.py   ✅ Chat history storage          ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Document Types for Classification

The CNN will classify these **7 document categories** specific to Philippine MSME lending:

| Class | PH Document Examples | Purpose |
|-------|---------------------|---------|
| `valid_id` | PhilSys National ID, Driver's License, Passport, UMID, SSS ID, Postal ID, Voter's ID, PRC ID | Identity verification |
| `selfie_with_id` | Selfie holding any valid ID | Anti-fraud verification |
| `business_permit` | DTI Certificate, Mayor's Permit, Barangay Business Permit, SEC Registration | Business legitimacy |
| `proof_of_address` | Meralco/Manila Water bill, Barangay Certificate of Residency, Lease contract | Address verification |
| `business_photo` | Photo of sari-sari store, market stall, home-based setup, inventory | Business existence proof |
| `income_proof` | Bank statements, GCash/Maya screenshots, Sales logbook, Official receipts | Income verification (optional) |
| `invalid` | Blurry images, random photos, memes, screenshots | Negative samples for rejection |

---

# Phase 1: CNN Training Data Collection

## Duration: 2-3 Days

### Task 1.1: Create Folder Structure

```bash
documents/ml/training_data/
├── valid_id/           # Target: 50-100 images
├── selfie_with_id/     # Target: 30-50 images
├── business_permit/    # Target: 30-50 images
├── proof_of_address/   # Target: 30-50 images
├── business_photo/     # Target: 30-50 images
├── income_proof/       # Target: 30-50 images
└── invalid/            # Target: 50-100 images
```

**Total Target: 270-500 images minimum**

### Task 1.2: Data Sources for Philippine Documents

#### Source A: Kaggle Datasets (Recommended)

| Dataset | URL | Use For |
|---------|-----|---------|
| ID Card Dataset | https://www.kaggle.com/datasets/trainingdatapro/identity-document-image-dataset | `valid_id` |
| Document Classification | https://www.kaggle.com/datasets/shaz13/real-world-documents-collections | `business_permit`, `proof_of_address` |
| Face + ID | https://www.kaggle.com/search?q=face+id+verification | `selfie_with_id` |
| Receipt/Invoice | https://www.kaggle.com/search?q=receipt+invoice | `income_proof` |

#### Source B: Roboflow Universe

| Dataset | URL | Use For |
|---------|-----|---------|
| ID Document Detection | https://universe.roboflow.com/search?q=id+card | `valid_id` |
| Document Type | https://universe.roboflow.com/search?q=document+classification | Multiple |

#### Source C: MIDV-500/MIDV-2020 (ID Documents)

- **URL:** https://github.com/fcakyon/midv500
- **Contains:** 500 ID documents from various countries
- **Use For:** `valid_id` class

#### Source D: Generate Synthetic/Sample Data

For categories hard to find online:

| Category | How to Generate |
|----------|-----------------|
| `selfie_with_id` | Team members take sample selfies holding printed ID templates |
| `business_permit` | Find permit templates online, fill with fake data |
| `business_photo` | Take photos of local sari-sari stores, market stalls |
| `income_proof` | Screenshot fake GCash/bank statement templates |
| `invalid` | Random photos, memes, blurry screenshots, partial documents |

#### Source E: Philippine-Specific Resources

| Resource | What to Get |
|----------|-------------|
| Sample Philippine IDs | Search "Philippine ID sample" (blur sensitive data) |
| DTI Certificate template | Search "DTI certificate sample" |
| Mayor's Permit sample | Search "Mayor's permit sample Philippines" |
| Barangay Certificate | Search "Barangay certificate sample" |
| Utility Bill samples | Meralco, Manila Water bill templates |

### Task 1.3: Image Requirements

| Requirement | Specification |
|-------------|---------------|
| **Format** | JPEG (.jpg, .jpeg) or PNG (.png) |
| **Minimum Size** | 224 x 224 pixels (will be resized) |
| **Recommended Size** | 640 x 480 or higher |
| **Quality** | Clear, readable, properly lit |
| **Orientation** | Upright preferred, but include some rotated |
| **Variations** | Include different lighting, angles, backgrounds |

### Task 1.4: Data Augmentation (Automatic)

The training script already applies augmentation:
- Random crop
- Horizontal flip
- Rotation (±10°)
- Color jitter (brightness, contrast)

No need to manually create variations.

---

# Phase 2: CNN Model Training

## Duration: 1-2 Hours

### Task 2.1: Verify Training Data

```bash
# Check folder structure and image counts
ls -la documents/ml/training_data/
```

Expected output:
```
valid_id/           (50+ images)
selfie_with_id/     (30+ images)
business_permit/    (30+ images)
proof_of_address/   (30+ images)
business_photo/     (30+ images)
income_proof/       (30+ images)
invalid/            (50+ images)
```

### Task 2.2: Install Dependencies

```bash
pip install torch torchvision opencv-python pillow
```

### Task 2.3: Run Training

```bash
# Basic training (10 epochs, frozen backbone)
python manage.py train_document_classifier

# Extended training (20 epochs)
python manage.py train_document_classifier --epochs 20

# Fine-tune entire model (if accuracy is low)
python manage.py train_document_classifier --epochs 20 --fine-tune

# Adjust batch size for memory issues
python manage.py train_document_classifier --batch-size 16
```

### Task 2.4: Training Output

After training completes:

```
documents/ml/models/
├── document_classifier.pth    # Trained model weights (~14MB)
└── model_config.json          # Model configuration
```

### Task 2.5: Expected Accuracy

| Metric | Target | Acceptable |
|--------|--------|------------|
| Validation Accuracy | >85% | >75% |
| Per-class Accuracy | >80% | >70% |

If accuracy is below target:
1. Add more training images
2. Use `--fine-tune` flag
3. Increase epochs to 30-50

---

# Phase 3: CNN Testing & Integration

## Duration: 1 Day

### Task 3.1: Verify Model Loading

The model auto-loads when Django starts. Check logs:

```bash
python manage.py runserver
# Look for: "CNN model loaded successfully"
```

### Task 3.2: Test Document Classification

**Upload a test document:**

```bash
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@test_id.jpg" \
  -F "document_type=valid_id"
```

**Expected response with CNN:**

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
      "predicted_type": "valid_id",
      "type_confidence": 0.92,
      "analysis_mode": "cnn"
    }
  }
}
```

### Task 3.3: Test Document Mismatch Detection

Upload wrong document type:

```bash
# Upload a business_photo as valid_id
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@sari_sari_store.jpg" \
  -F "document_type=valid_id"
```

CNN should detect mismatch:
- `predicted_type`: "business_photo"
- `type_confidence`: 0.87
- Status should be `needs_review`

### Task 3.4: Test Invalid Document Detection

Upload random/invalid image:

```bash
curl -X POST http://localhost:8000/api/documents/upload/ \
  -H "Authorization: Bearer <token>" \
  -F "file=@random_meme.jpg" \
  -F "document_type=valid_id"
```

CNN should flag as invalid:
- `predicted_type`: "invalid"
- Status: `needs_review`

---

# Phase 4: NLP Enhancement (After CNN)

## Duration: 2-3 Days

### Task 4.1: Configure Groq API

Add to `.env`:
```env
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx
GROQ_MODEL=llama-3.1-8b-instant
```

### Task 4.2: RAG System (Knowledge Base)

Create a knowledge base service that:
1. Stores loan education content
2. Stores FAQs and their answers
3. AI retrieves relevant info before responding

**New file:** `ai_assistant/services/rag_service.py`

### Task 4.3: Context-Aware Responses

Enhance AI prompts with user context:
- Profile completion status
- Business type
- Document upload status
- Loan application status

**New file:** `ai_assistant/services/context_service.py`

### Task 4.4: Document Status Integration

AI can check and explain:
- Which documents are uploaded
- Which documents are pending/rejected
- What documents are still needed

### Task 4.5: Loan Pre-Qualification Logic

AI evaluates eligibility based on:
- Profile completeness
- Document status
- Business information
- Alternative data

---

# Phase 5: CNN + NLP Integration

## Duration: 1-2 Days

### Task 5.1: AI Document Feedback

When CNN rejects a document, AI explains:
- Why the document was rejected
- How to take a better photo
- Tips for each document type

### Task 5.2: Smart Document Guidance

AI proactively helps with:
- "Your ID photo looks blurry. Try taking it in better lighting."
- "The business permit is hard to read. Please upload a clearer copy."

### Task 5.3: Intelligent Prompting

CNN results feed into NLP:
- CNN predicts document type → AI confirms with user
- CNN detects low quality → AI suggests improvements
- CNN flags mismatch → AI asks for correct document

---

# Phase 6: Testing & Optimization

## Duration: 1-2 Days

### Task 6.1: End-to-End Testing

| Test Case | Expected Result |
|-----------|-----------------|
| Upload valid ID | CNN classifies correctly, high confidence |
| Upload blurry document | CNN flags for review, AI suggests retake |
| Upload wrong document type | CNN detects mismatch, AI asks for correct type |
| Chat about loan | AI responds with context-aware advice |
| Ask about documents | AI shows upload status and guides next steps |

### Task 6.2: Accuracy Metrics

| Metric | Target |
|--------|--------|
| CNN Classification Accuracy | >85% |
| CNN Type Mismatch Detection | >90% |
| CNN Invalid Detection | >80% |
| AI Response Relevance | User satisfaction surveys |

### Task 6.3: Performance Optimization

| Metric | Target |
|--------|--------|
| CNN Inference Time | <1 second |
| AI Response Time | <3 seconds |
| Document Upload + Analysis | <5 seconds |

---

# Timeline Summary

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| **Phase 1:** Data Collection | 2-3 days | None |
| **Phase 2:** CNN Training | 1-2 hours | Phase 1 complete |
| **Phase 3:** CNN Testing | 1 day | Phase 2 complete |
| **Phase 4:** NLP Enhancement | 2-3 days | Groq API key |
| **Phase 5:** CNN + NLP Integration | 1-2 days | Phase 3 & 4 complete |
| **Phase 6:** Testing & Optimization | 1-2 days | Phase 5 complete |

**Total Estimated Time: 7-12 days**

---

# Quick Start Checklist

## CNN (Start Now)

- [ ] Create folder structure in `documents/ml/training_data/`
- [ ] Download ID card dataset from Kaggle
- [ ] Collect/generate Philippine-specific documents
- [ ] Organize images into 7 categories
- [ ] Verify minimum 30-50 images per category
- [ ] Install PyTorch dependencies
- [ ] Run `python manage.py train_document_classifier`
- [ ] Verify model saved to `documents/ml/models/`
- [ ] Test document upload with CNN analysis
- [ ] Verify classification accuracy >85%

## NLP (After CNN or Parallel)

- [ ] Get Groq API key from PM
- [ ] Add `GROQ_API_KEY` to `.env`
- [ ] Test chat endpoint works
- [ ] Create RAG service for knowledge base
- [ ] Create context service for user data
- [ ] Integrate document status into AI
- [ ] Add loan pre-qualification logic

## Integration

- [ ] CNN results feed into NLP prompts
- [ ] AI explains document rejections
- [ ] AI guides document re-uploads
- [ ] End-to-end testing complete

---

# Files to Create/Modify

## Phase 1-3 (CNN)

| File | Action | Description |
|------|--------|-------------|
| `documents/ml/training_data/*/` | Create folders | 7 category folders |
| `documents/ml/training_data/*/*.jpg` | Add images | Training data |
| `documents/ml/models/document_classifier.pth` | Generated | Trained model |
| `documents/ml/models/model_config.json` | Generated | Model config |

## Phase 4-5 (NLP)

| File | Action | Description |
|------|--------|-------------|
| `ai_assistant/services/rag_service.py` | Create | Knowledge base service |
| `ai_assistant/services/context_service.py` | Create | User context builder |
| `ai_assistant/services/prequalify_service.py` | Create | Loan eligibility logic |
| `ai_assistant/services/llm_service.py` | Modify | Add context integration |

---

# Success Criteria

| Criteria | Measurement |
|----------|-------------|
| ✅ CNN classifies documents | >85% accuracy on test set |
| ✅ CNN detects invalid documents | >80% detection rate |
| ✅ AI responds contextually | Uses profile/document data |
| ✅ AI explains document issues | Clear, helpful feedback |
| ✅ System guides users | From registration to loan application |
| ✅ Performance acceptable | <5 second total response time |

---

**Next Step:** Start Phase 1 - Create training data folders and begin collecting images.

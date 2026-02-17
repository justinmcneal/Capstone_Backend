# CNN Model Improvements Playbook

> **Companion to:** [CNN_FINAL_GUIDE.md](CNN_FINAL_GUIDE.md)
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

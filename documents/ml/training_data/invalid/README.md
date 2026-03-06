# Invalid - Training Data (Negative Samples)

## What Goes Here
Images that should be REJECTED by the classifier.

## Purpose
Train the model to recognize and reject:
- Random non-document images
- Blurry/unreadable documents
- Partial/cropped documents
- Wrong file types (screenshots of apps, memes, etc.)

## Types of Invalid Images to Collect

### Category 1: Random Images
- Nature photos (landscapes, animals, plants)
- Food photos
- Selfies without ID
- Screenshots of apps/games
- Memes and social media posts
- Product photos

### Category 2: Poor Quality Documents
- Very blurry document photos
- Extremely dark/overexposed images
- Documents with flash glare
- Partial/cropped documents
- Upside down documents
- Documents too far away

### Category 3: Wrong Documents
- Foreign documents (non-Philippine)
- Expired/cancelled documents
- Handwritten notes (not official documents)
- Screenshots of websites
- Digital forms (not actual documents)

### Category 4: Manipulation Attempts
- Edited/photoshopped documents
- Documents with visible alterations
- Multiple documents in one image
- Documents on screens (not physical)

## Image Requirements
- **Format:** JPG, JPEG, or PNG
- **Minimum Size:** 224 x 224 pixels
- **Quality:** Various (include poor quality on purpose)
- **Content:** Anything that should NOT be accepted

## Target Count
**50-100 images minimum**

This class needs MORE samples because it covers many scenarios.

## Where to Find
1. **Your phone gallery:** Random photos
2. **Google Images:** Random objects, nature, food
3. **Meme sites:** Random memes
4. **Take blurry photos:** Intentionally blur real documents
5. **Screenshots:** Random app screenshots

## Easy to Collect
This is the EASIEST category:
- Just use random photos from your phone
- Take intentionally bad photos of paper
- Screenshot random apps/websites
- Download random memes

## Sample Categories to Mix
- 20% random nature/object photos
- 20% blurry document photos
- 20% random selfies (without ID)
- 20% screenshots/memes
- 20% partial/cropped documents

## ⚠️ Note
- This class helps prevent fraud
- Users trying to upload fake documents will be flagged
- Model learns what a "real document" looks like by contrast

#!/usr/bin/env python3
"""
Check training data quality and counts before training CNN model.

Usage:
    python scripts/check_training_data.py
"""
import sys
from pathlib import Path
from collections import defaultdict
from PIL import Image

# Add Django settings if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

# Expected classes
EXPECTED_CLASSES = [
    'valid_id',
    'selfie_with_id',
    'business_permit',
    'proof_of_address',
    'business_photo',
    'income_proof',
    'invalid'
]

# Minimum requirements
MIN_SIZE = (224, 224)
MIN_SAMPLES_PER_CLASS = 30
RECOMMENDED_SAMPLES = 80


def check_training_data():
    """Check training data folder for issues."""
    
    # Find training data folder
    project_root = Path(__file__).parent.parent
    training_data_path = project_root / 'documents' / 'ml' / 'training_data'
    
    if not training_data_path.exists():
        print(f"❌ Training data folder not found: {training_data_path}")
        return False
    
    print("=" * 60)
    print("CNN TRAINING DATA CHECK")
    print("=" * 60)
    print()
    
    issues = []
    warnings = []
    stats = defaultdict(lambda: {
        'count': 0,
        'too_small': [],
        'corrupted': [],
        'avg_size': [0, 0]
    })
    
    # Check each class folder
    for class_name in EXPECTED_CLASSES:
        class_path = training_data_path / class_name
        
        if not class_path.exists():
            issues.append(f"Missing folder: {class_name}/")
            continue
        
        # Count images
        image_files = list(class_path.glob('*.jpg')) + \
                     list(class_path.glob('*.jpeg')) + \
                     list(class_path.glob('*.png'))
        
        stats[class_name]['count'] = len(image_files)
        
        # Check each image
        widths, heights = [], []
        for img_path in image_files:
            try:
                img = Image.open(img_path)
                width, height = img.size
                widths.append(width)
                heights.append(height)
                
                # Check size
                if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
                    stats[class_name]['too_small'].append(img_path.name)
                
                img.close()
                
            except Exception as e:
                stats[class_name]['corrupted'].append(img_path.name)
        
        # Calculate average size
        if widths and heights:
            stats[class_name]['avg_size'] = [
                sum(widths) // len(widths),
                sum(heights) // len(heights)
            ]
        
        # Check sample count
        if stats[class_name]['count'] == 0:
            issues.append(f"{class_name}: No images found")
        elif stats[class_name]['count'] < MIN_SAMPLES_PER_CLASS:
            warnings.append(
                f"{class_name}: Only {stats[class_name]['count']} images "
                f"(minimum: {MIN_SAMPLES_PER_CLASS})"
            )
        elif stats[class_name]['count'] < RECOMMENDED_SAMPLES:
            warnings.append(
                f"{class_name}: {stats[class_name]['count']} images "
                f"(recommended: {RECOMMENDED_SAMPLES}+)"
            )
    
    # Print results
    print("📊 SAMPLE COUNTS")
    print("-" * 60)
    total_samples = 0
    for class_name in EXPECTED_CLASSES:
        count = stats[class_name]['count']
        total_samples += count
        
        status = "✅"
        if count == 0:
            status = "❌"
        elif count < MIN_SAMPLES_PER_CLASS:
            status = "⚠️"
        elif count < RECOMMENDED_SAMPLES:
            status = "🟡"
        
        avg_w, avg_h = stats[class_name]['avg_size']
        size_info = f"{avg_w}x{avg_h}" if avg_w > 0 else "N/A"
        
        print(f"{status} {class_name:20} {count:4} images  (avg size: {size_info})")
    
    print("-" * 60)
    print(f"   TOTAL:              {total_samples:4} images")
    print()
    
    # Image quality issues
    quality_issues_found = False
    for class_name in EXPECTED_CLASSES:
        if stats[class_name]['too_small']:
            if not quality_issues_found:
                print("⚠️  IMAGE QUALITY ISSUES")
                print("-" * 60)
                quality_issues_found = True
            
            print(f"{class_name}: {len(stats[class_name]['too_small'])} images too small")
            for fname in stats[class_name]['too_small'][:3]:
                print(f"  - {fname}")
            if len(stats[class_name]['too_small']) > 3:
                print(f"  ... and {len(stats[class_name]['too_small']) - 3} more")
        
        if stats[class_name]['corrupted']:
            if not quality_issues_found:
                print("⚠️  IMAGE QUALITY ISSUES")
                print("-" * 60)
                quality_issues_found = True
            
            print(f"{class_name}: {len(stats[class_name]['corrupted'])} corrupted images")
            for fname in stats[class_name]['corrupted']:
                print(f"  - {fname}")
    
    if quality_issues_found:
        print()
    
    # Print warnings
    if warnings:
        print("⚠️  WARNINGS")
        print("-" * 60)
        for warning in warnings:
            print(f"  {warning}")
        print()
    
    # Print critical issues
    if issues:
        print("❌ CRITICAL ISSUES")
        print("-" * 60)
        for issue in issues:
            print(f"  {issue}")
        print()
    
    # Verdict
    print("=" * 60)
    if issues:
        print("❌ NOT READY FOR TRAINING")
        print("   Fix critical issues first.")
    elif warnings:
        print("🟡 MINIMUM REQUIREMENTS MET")
        print("   Can train, but more data recommended for better accuracy.")
        print(f"   Current: {total_samples} images")
        print(f"   Recommended: {RECOMMENDED_SAMPLES * len(EXPECTED_CLASSES)}+ images")
    else:
        print("✅ READY FOR TRAINING!")
        print(f"   {total_samples} images collected across {len(EXPECTED_CLASSES)} classes")
        print()
        print("   Run: python manage.py train_document_classifier")
    print("=" * 60)
    
    return not issues


if __name__ == '__main__':
    try:
        success = check_training_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

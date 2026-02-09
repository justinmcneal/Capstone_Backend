#!/usr/bin/env python3
"""
Test trained CNN model on sample images.

Usage:
    python scripts/test_cnn_model.py <image_path>
    python scripts/test_cnn_model.py <folder_path> --batch
"""
import sys
from pathlib import Path

# Add Django to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Setup Django
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from documents.services.analyzer import analyze_document
from documents.services.cnn_model import DOCUMENT_CLASSES


def test_single_image(image_path):
    """Test a single image."""
    print(f"\n{'='*60}")
    print(f"Testing: {image_path.name}")
    print('='*60)
    
    result = analyze_document(str(image_path))
    
    print("\n📊 ANALYSIS RESULTS:")
    print(f"  Mode:             {result.get('analysis_mode', 'N/A')}")
    print(f"  Model Available:  {result.get('model_available', False)}")
    print(f"  Valid:            {result.get('is_valid', False)}")
    print(f"  Quality Score:    {result.get('quality_score', 0):.2f}")
    
    if result.get('quality_issues'):
        print(f"  Quality Issues:   {', '.join(result['quality_issues'])}")
    else:
        print(f"  Quality Issues:   None")
    
    if result.get('predicted_type'):
        print(f"\n🎯 CLASSIFICATION:")
        print(f"  Predicted Type:   {result['predicted_type']}")
        if result.get('type_confidence') is not None:
            conf = result['type_confidence'] * 100
            print(f"  Confidence:       {conf:.1f}%")
            
            # Confidence interpretation
            if conf >= 90:
                print(f"  Interpretation:   ✅ Very confident")
            elif conf >= 75:
                print(f"  Interpretation:   ✅ Confident")
            elif conf >= 60:
                print(f"  Interpretation:   ⚠️  Uncertain")
            else:
                print(f"  Interpretation:   ❌ Low confidence")
    
    print('='*60)


def test_folder(folder_path):
    """Test all images in a folder."""
    image_files = list(folder_path.glob('*.jpg')) + \
                 list(folder_path.glob('*.jpeg')) + \
                 list(folder_path.glob('*.png'))
    
    if not image_files:
        print(f"❌ No images found in {folder_path}")
        return
    
    print(f"\n{'='*60}")
    print(f"Testing {len(image_files)} images from {folder_path.name}/")
    print('='*60)
    
    # Class distribution
    class_counts = {cls: 0 for cls in DOCUMENT_CLASSES}
    confidence_scores = []
    quality_scores = []
    
    for img_path in image_files:
        result = analyze_document(str(img_path))
        
        predicted = result.get('predicted_type', 'unknown')
        confidence = result.get('type_confidence', 0)
        quality = result.get('quality_score', 0)
        
        if predicted in class_counts:
            class_counts[predicted] += 1
        
        if confidence is not None:
            confidence_scores.append(confidence)
        quality_scores.append(quality)
        
        # Print result
        conf_str = f"{confidence*100:.1f}%" if confidence else "N/A"
        print(f"  {img_path.name:30} → {predicted:20} ({conf_str})")
    
    # Summary statistics
    print(f"\n{'='*60}")
    print("SUMMARY STATISTICS")
    print('='*60)
    
    print("\n📊 Classification Distribution:")
    for cls, count in sorted(class_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            pct = count / len(image_files) * 100
            print(f"  {cls:20} {count:3} ({pct:.1f}%)")
    
    if confidence_scores:
        avg_conf = sum(confidence_scores) / len(confidence_scores) * 100
        min_conf = min(confidence_scores) * 100
        max_conf = max(confidence_scores) * 100
        
        print(f"\n🎯 Confidence Metrics:")
        print(f"  Average:  {avg_conf:.1f}%")
        print(f"  Range:    {min_conf:.1f}% - {max_conf:.1f}%")
    
    if quality_scores:
        avg_quality = sum(quality_scores) / len(quality_scores) * 100
        print(f"\n✨ Average Quality Score: {avg_quality:.1f}%")
    
    print('='*60)


def confusion_matrix_test(test_data_path):
    """
    Test model accuracy with labeled test data.
    
    Expected structure:
    test_data/
      ├── valid_id/
      ├── selfie_with_id/
      └── ...
    """
    test_path = Path(test_data_path)
    
    if not test_path.exists():
        print(f"❌ Test data folder not found: {test_path}")
        return
    
    print(f"\n{'='*60}")
    print("CONFUSION MATRIX TEST")
    print('='*60)
    
    results = {cls: {'correct': 0, 'wrong': 0, 'misclassified_as': {}} 
               for cls in DOCUMENT_CLASSES}
    
    total_correct = 0
    total_wrong = 0
    
    for class_dir in test_path.iterdir():
        if not class_dir.is_dir() or class_dir.name not in DOCUMENT_CLASSES:
            continue
        
        true_label = class_dir.name
        image_files = list(class_dir.glob('*.jpg')) + \
                     list(class_dir.glob('*.jpeg')) + \
                     list(class_dir.glob('*.png'))
        
        print(f"\nTesting {true_label}: {len(image_files)} images")
        
        for img_path in image_files:
            result = analyze_document(str(img_path))
            predicted = result.get('predicted_type', 'unknown')
            
            if predicted == true_label:
                results[true_label]['correct'] += 1
                total_correct += 1
                print(f"  ✓ {img_path.name}")
            else:
                results[true_label]['wrong'] += 1
                total_wrong += 1
                
                # Track misclassification
                if predicted not in results[true_label]['misclassified_as']:
                    results[true_label]['misclassified_as'][predicted] = 0
                results[true_label]['misclassified_as'][predicted] += 1
                
                print(f"  ✗ {img_path.name}: predicted {predicted}")
    
    # Print summary
    print(f"\n{'='*60}")
    print("ACCURACY BY CLASS")
    print('='*60)
    
    for cls in DOCUMENT_CLASSES:
        correct = results[cls]['correct']
        wrong = results[cls]['wrong']
        total = correct + wrong
        
        if total == 0:
            continue
        
        accuracy = correct / total * 100
        status = "✅" if accuracy >= 85 else "⚠️" if accuracy >= 70 else "❌"
        
        print(f"\n{status} {cls}:")
        print(f"  Accuracy: {accuracy:.1f}% ({correct}/{total})")
        
        if results[cls]['misclassified_as']:
            print(f"  Misclassified as:")
            for pred, count in sorted(results[cls]['misclassified_as'].items(),
                                     key=lambda x: -x[1]):
                print(f"    - {pred}: {count}")
    
    # Overall accuracy
    total = total_correct + total_wrong
    if total > 0:
        overall_accuracy = total_correct / total * 100
        print(f"\n{'='*60}")
        print(f"OVERALL ACCURACY: {overall_accuracy:.1f}% ({total_correct}/{total})")
        
        if overall_accuracy >= 90:
            print("✅ Excellent! Production-ready.")
        elif overall_accuracy >= 85:
            print("✅ Good! Ready for testing.")
        elif overall_accuracy >= 70:
            print("⚠️  Acceptable, but needs improvement.")
        else:
            print("❌ Low accuracy. Retrain with more data.")
        
        print('='*60)


def main():
    """Main entry point."""
    
    if len(sys.argv) < 2:
        print("CNN Model Testing Tool")
        print("\nUsage:")
        print("  Single image:     python scripts/test_cnn_model.py <image_path>")
        print("  Batch folder:     python scripts/test_cnn_model.py <folder_path> --batch")
        print("  Confusion matrix: python scripts/test_cnn_model.py <test_data_path> --confusion")
        print("\nExamples:")
        print("  python scripts/test_cnn_model.py ~/Downloads/my_id.jpg")
        print("  python scripts/test_cnn_model.py ~/test_images/ --batch")
        print("  python scripts/test_cnn_model.py documents/ml/test_data/ --confusion")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    
    if not path.exists():
        print(f"❌ Path not found: {path}")
        sys.exit(1)
    
    # Check if model is available
    from documents.services.analyzer import get_analyzer
    analyzer = get_analyzer()
    
    if not analyzer.model_loaded:
        print("❌ No trained CNN model found!")
        print("\nTrain the model first:")
        print("  python manage.py train_document_classifier")
        sys.exit(1)
    
    print(f"✅ CNN model loaded successfully")
    
    # Determine test mode
    if '--confusion' in sys.argv:
        confusion_matrix_test(path)
    elif path.is_file():
        test_single_image(path)
    elif path.is_dir():
        if '--batch' in sys.argv:
            test_folder(path)
        else:
            # Default to batch mode for folders
            test_folder(path)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

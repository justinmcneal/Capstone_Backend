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
    Test model accuracy with labeled test data and generate visual reports.
    
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
    
    # Collect per-image data for charts
    all_true_labels = []
    all_pred_labels = []
    all_confidences = []
    
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
            confidence = result.get('type_confidence', 0) or 0
            
            all_true_labels.append(true_label)
            all_pred_labels.append(predicted)
            all_confidences.append(confidence)
            
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
    
    # Print text summary
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
    
    # Generate visual reports
    _generate_evaluation_charts(results, all_true_labels, all_pred_labels, all_confidences)


def _generate_evaluation_charts(results, true_labels, pred_labels, confidences):
    """Generate and save evaluation charts with matplotlib."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("\n⚠️  matplotlib not installed. Run: pip install matplotlib")
        print("Skipping visual reports.")
        return
    
    reports_dir = Path(__file__).parent.parent / 'documents' / 'ml' / 'reports'
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Filter to only classes that appear in test data
    active_classes = sorted(set(true_labels + pred_labels))
    if not active_classes:
        print("No test data to visualize.")
        return
    
    print(f"\n{'='*60}")
    print("GENERATING VISUAL REPORTS")
    print('='*60)
    
    # --- Chart 1: Confusion Matrix Heatmap ---
    n = len(active_classes)
    cm = np.zeros((n, n), dtype=int)
    class_to_idx = {cls: i for i, cls in enumerate(active_classes)}
    
    for true, pred in zip(true_labels, pred_labels):
        if true in class_to_idx and pred in class_to_idx:
            cm[class_to_idx[true]][class_to_idx[pred]] += 1
    
    fig1, ax1 = plt.subplots(figsize=(10, 8))
    im = ax1.imshow(cm, interpolation='nearest', cmap='Blues')
    ax1.set_title('Confusion Matrix', fontsize=16, fontweight='bold', pad=15)
    fig1.colorbar(im, ax=ax1, shrink=0.8)
    
    ax1.set_xticks(range(n))
    ax1.set_yticks(range(n))
    short_labels = [c.replace('_', '\n') for c in active_classes]
    ax1.set_xticklabels(short_labels, fontsize=10)
    ax1.set_yticklabels(short_labels, fontsize=10)
    ax1.set_xlabel('Predicted', fontsize=13, fontweight='bold')
    ax1.set_ylabel('True Label', fontsize=13, fontweight='bold')
    
    # Annotate cells
    thresh = cm.max() / 2.0
    for i in range(n):
        for j in range(n):
            color = 'white' if cm[i, j] > thresh else 'black'
            ax1.text(j, i, str(cm[i, j]), ha='center', va='center',
                     fontsize=14, fontweight='bold', color=color)
    
    plt.tight_layout()
    fig1.savefig(reports_dir / 'confusion_matrix.png', dpi=150, bbox_inches='tight')
    plt.close(fig1)
    print(f"📊 Saved: {reports_dir / 'confusion_matrix.png'}")
    
    # --- Chart 2: Per-Class Accuracy Bar Chart ---
    class_names = []
    accuracies = []
    sample_counts = []
    
    for cls in active_classes:
        correct = results.get(cls, {}).get('correct', 0)
        wrong = results.get(cls, {}).get('wrong', 0)
        total = correct + wrong
        if total > 0:
            class_names.append(cls)
            accuracies.append(correct / total * 100)
            sample_counts.append(total)
    
    if class_names:
        fig2, ax2 = plt.subplots(figsize=(10, 6))
        y_pos = range(len(class_names))
        bar_colors = ['#2ecc71' if a >= 85 else '#f39c12' if a >= 70 else '#e74c3c' for a in accuracies]
        
        bars = ax2.barh(y_pos, accuracies, color=bar_colors, edgecolor='black', linewidth=0.8, height=0.6)
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels(class_names, fontsize=11)
        ax2.set_xlabel('Accuracy (%)', fontsize=12)
        ax2.set_title('Per-Class Accuracy', fontsize=14, fontweight='bold')
        ax2.set_xlim([0, 110])
        ax2.axvline(x=85, color='green', linestyle='--', linewidth=1.5, alpha=0.5, label='Target (85%)')
        ax2.grid(axis='x', alpha=0.3)
        ax2.legend(fontsize=11)
        
        # Add labels
        for i, (acc, count) in enumerate(zip(accuracies, sample_counts)):
            ax2.text(acc + 1, i, f'{acc:.0f}% ({count} imgs)', va='center', fontsize=10, fontweight='bold')
        
        plt.tight_layout()
        fig2.savefig(reports_dir / 'per_class_accuracy.png', dpi=150, bbox_inches='tight')
        plt.close(fig2)
        print(f"📊 Saved: {reports_dir / 'per_class_accuracy.png'}")
    
    # --- Chart 3: Confidence Distribution Histogram ---
    if confidences:
        fig3, ax3 = plt.subplots(figsize=(10, 6))
        
        correct_conf = [c for c, t, p in zip(confidences, true_labels, pred_labels) if t == p]
        wrong_conf = [c for c, t, p in zip(confidences, true_labels, pred_labels) if t != p]
        
        bins = np.linspace(0, 1, 21)
        if correct_conf:
            ax3.hist(correct_conf, bins=bins, alpha=0.7, color='#2ecc71', edgecolor='black',
                     linewidth=0.8, label=f'Correct ({len(correct_conf)})')
        if wrong_conf:
            ax3.hist(wrong_conf, bins=bins, alpha=0.7, color='#e74c3c', edgecolor='black',
                     linewidth=0.8, label=f'Wrong ({len(wrong_conf)})')
        
        ax3.axvline(x=0.80, color='orange', linestyle='--', linewidth=2, label='Threshold (0.80)')
        ax3.set_xlabel('Confidence Score', fontsize=12)
        ax3.set_ylabel('Number of Predictions', fontsize=12)
        ax3.set_title('Confidence Distribution', fontsize=14, fontweight='bold')
        ax3.legend(fontsize=11)
        ax3.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        fig3.savefig(reports_dir / 'confidence_distribution.png', dpi=150, bbox_inches='tight')
        plt.close(fig3)
        print(f"📊 Saved: {reports_dir / 'confidence_distribution.png'}")
    
    # --- Chart 4: Precision / Recall / F1 ---
    pr_classes = []
    precisions = []
    recalls = []
    f1_scores = []
    
    for cls in active_classes:
        tp = results.get(cls, {}).get('correct', 0)
        fn = results.get(cls, {}).get('wrong', 0)
        fp = sum(1 for t, p in zip(true_labels, pred_labels) if p == cls and t != cls)
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        if (tp + fn) > 0:  # Only include classes with test data
            pr_classes.append(cls)
            precisions.append(precision * 100)
            recalls.append(recall * 100)
            f1_scores.append(f1 * 100)
    
    if pr_classes:
        fig4, ax4 = plt.subplots(figsize=(12, 6))
        x = np.arange(len(pr_classes))
        width = 0.25
        
        bars1 = ax4.bar(x - width, precisions, width, label='Precision', color='#3498db', edgecolor='black', linewidth=0.8)
        bars2 = ax4.bar(x, recalls, width, label='Recall', color='#2ecc71', edgecolor='black', linewidth=0.8)
        bars3 = ax4.bar(x + width, f1_scores, width, label='F1 Score', color='#e67e22', edgecolor='black', linewidth=0.8)
        
        ax4.set_xlabel('Document Class', fontsize=12)
        ax4.set_ylabel('Score (%)', fontsize=12)
        ax4.set_title('Precision / Recall / F1 Score per Class', fontsize=14, fontweight='bold')
        ax4.set_xticks(x)
        ax4.set_xticklabels(pr_classes, fontsize=10, rotation=20)
        ax4.set_ylim([0, 115])
        ax4.legend(fontsize=11)
        ax4.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        fig4.savefig(reports_dir / 'precision_recall_f1.png', dpi=150, bbox_inches='tight')
        plt.close(fig4)
        print(f"📊 Saved: {reports_dir / 'precision_recall_f1.png'}")
    
    # --- Chart 5: Error Breakdown Pie Chart ---
    error_counts = {}
    for true, pred in zip(true_labels, pred_labels):
        if true != pred:
            key = f"{true} → {pred}"
            error_counts[key] = error_counts.get(key, 0) + 1
    
    if error_counts:
        fig5, ax5 = plt.subplots(figsize=(10, 8))
        labels = list(error_counts.keys())
        sizes = list(error_counts.values())
        colors = plt.cm.Set2(np.linspace(0, 1, len(labels)))
        
        wedges, texts, autotexts = ax5.pie(
            sizes, labels=None, autopct='%1.0f%%',
            colors=colors, startangle=90,
            pctdistance=0.85, textprops={'fontsize': 11}
        )
        ax5.legend(wedges, [f"{l} ({s})" for l, s in zip(labels, sizes)],
                   title="Misclassification Type", loc="center left",
                   bbox_to_anchor=(1, 0, 0.5, 1), fontsize=10)
        ax5.set_title('Error Breakdown', fontsize=14, fontweight='bold')
        
        plt.tight_layout()
        fig5.savefig(reports_dir / 'error_breakdown.png', dpi=150, bbox_inches='tight')
        plt.close(fig5)
        print(f"📊 Saved: {reports_dir / 'error_breakdown.png'}")
    
    print(f"\n✅ All charts saved to: {reports_dir}")
    print(f"   Open the PNG files to view your model's performance visually.")


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

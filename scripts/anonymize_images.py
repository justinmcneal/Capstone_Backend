#!/usr/bin/env python3
"""
Anonymize images by blurring specified regions.

Usage:
    python scripts/anonymize_images.py <folder_path>
    
Example:
    python scripts/anonymize_images.py ~/msme_cnn_data_temp/valid_id/
"""
import sys
from pathlib import Path
import cv2
import numpy as np


def blur_region(image_path, regions, output_path=None):
    """
    Blur specified rectangular regions in an image.
    
    Args:
        image_path: Path to input image
        regions: List of (x, y, width, height) tuples
        output_path: Path to save output (defaults to overwriting input)
    """
    img = cv2.imread(str(image_path))
    
    if img is None:
        print(f"❌ Could not load: {image_path}")
        return False
    
    for x, y, width, height in regions:
        # Extract region
        roi = img[y:y+height, x:x+width]
        
        # Apply strong blur
        blurred = cv2.GaussianBlur(roi, (99, 99), 30)
        
        # Replace region
        img[y:y+height, x:x+width] = blurred
    
    # Save
    output = output_path or image_path
    cv2.imwrite(str(output), img)
    
    return True


def interactive_blur(image_path):
    """
    Interactive tool to select regions to blur.
    Click and drag to select regions.
    """
    print(f"\nBlurring: {image_path.name}")
    print("Instructions:")
    print("  - Click and drag to select region to blur")
    print("  - Press 's' to save")
    print("  - Press 'r' to reset")
    print("  - Press 'q' to quit")
    
    img = cv2.imread(str(image_path))
    if img is None:
        print(f"❌ Could not load: {image_path}")
        return
    
    clone = img.copy()
    rectangles = []
    drawing = False
    ix, iy = -1, -1
    
    def draw_rectangle(event, x, y, flags, param):
        nonlocal ix, iy, drawing, img
        
        if event == cv2.EVENT_LBUTTONDOWN:
            drawing = True
            ix, iy = x, y
        
        elif event == cv2.EVENT_MOUSEMOVE:
            if drawing:
                temp = img.copy()
                cv2.rectangle(temp, (ix, iy), (x, y), (0, 255, 0), 2)
                cv2.imshow('image', temp)
        
        elif event == cv2.EVENT_LBUTTONUP:
            drawing = False
            cv2.rectangle(img, (ix, iy), (x, y), (0, 255, 0), 2)
            rectangles.append((min(ix, x), min(iy, y), abs(x - ix), abs(y - iy)))
            cv2.imshow('image', img)
    
    cv2.namedWindow('image')
    cv2.setMouseCallback('image', draw_rectangle)
    cv2.imshow('image', img)
    
    while True:
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('s'):
            # Apply blur
            if rectangles:
                blur_region(image_path, rectangles)
                print(f"✓ Saved with {len(rectangles)} blurred regions")
            break
        
        elif key == ord('r'):
            # Reset
            img = clone.copy()
            rectangles = []
            cv2.imshow('image', img)
        
        elif key == ord('q'):
            break
    
    cv2.destroyAllWindows()


def batch_blur_folder(folder_path, regions):
    """
    Apply same blur regions to all images in a folder.
    Useful when documents have consistent layout.
    
    Args:
        folder_path: Path to folder containing images
        regions: List of (x, y, width, height) tuples
    """
    folder = Path(folder_path)
    
    if not folder.exists():
        print(f"❌ Folder not found: {folder}")
        return
    
    image_files = list(folder.glob('*.jpg')) + \
                 list(folder.glob('*.jpeg')) + \
                 list(folder.glob('*.png'))
    
    print(f"Blurring {len(image_files)} images in {folder.name}/")
    
    success_count = 0
    for img_path in image_files:
        if blur_region(img_path, regions):
            success_count += 1
            print(f"✓ {img_path.name}")
        else:
            print(f"✗ {img_path.name}")
    
    print(f"\n✅ Processed {success_count}/{len(image_files)} images")


def main():
    """Main entry point."""
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Interactive mode: python scripts/anonymize_images.py <image_path>")
        print("  Batch mode:       python scripts/anonymize_images.py <folder_path> --batch")
        print()
        print("Example regions for Philippine ID:")
        print("  Name region:    (100, 50, 300, 50)")
        print("  ID number:      (100, 150, 300, 50)")
        print("  Address:        (100, 200, 350, 80)")
        print("  Signature:      (100, 300, 200, 60)")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    
    if not path.exists():
        print(f"❌ Path not found: {path}")
        sys.exit(1)
    
    try:
        import cv2
    except ImportError:
        print("❌ OpenCV not installed. Run: pip install opencv-python")
        sys.exit(1)
    
    if path.is_file():
        # Interactive mode for single image
        interactive_blur(path)
    
    elif path.is_dir() and '--batch' in sys.argv:
        # Batch mode - define regions for Philippine IDs
        print("Batch blur mode")
        print("Using common regions for Philippine IDs:")
        
        # Common regions for Philippine passport/driver's license
        regions = [
            (100, 50, 300, 50),   # Name
            (100, 150, 300, 50),  # ID number
            (100, 200, 350, 80),  # Address
            (100, 300, 200, 60),  # Signature
        ]
        
        print("Regions to blur:")
        for i, (x, y, w, h) in enumerate(regions, 1):
            print(f"  {i}. x={x}, y={y}, width={w}, height={h}")
        
        response = input("\nProceed with these regions? [y/N]: ")
        if response.lower() == 'y':
            batch_blur_folder(path, regions)
        else:
            print("Cancelled")
    
    else:
        # Process all images in folder interactively
        image_files = list(path.glob('*.jpg')) + \
                     list(path.glob('*.jpeg')) + \
                     list(path.glob('*.png'))
        
        print(f"Found {len(image_files)} images in {path.name}/")
        
        for img_path in image_files:
            interactive_blur(img_path)


if __name__ == '__main__':
    main()

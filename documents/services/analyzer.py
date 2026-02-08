"""
Document Analysis Service - Quality Check & CNN Classification

Currently implements:
- Quality checks (blur detection, size validation)
- Image preprocessing

Future (after training data collected):
- MobileNetV2 document classification
- Document type prediction
"""
import os
import logging
from pathlib import Path
from PIL import Image
import io

logger = logging.getLogger('documents')

# Configuration
MIN_IMAGE_SIZE = (200, 200)  # Minimum dimensions
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
BLUR_THRESHOLD = 100  # Laplacian variance threshold


class DocumentAnalyzer:
    """
    Analyzes uploaded documents for quality and classification.
    
    Current mode: Quality-check only
    Future mode: CNN classification with MobileNetV2
    """
    
    def __init__(self):
        self.model = None
        self.model_loaded = False
        self._try_load_model()
    
    def _try_load_model(self):
        """Try to load trained CNN model if available"""
        model_path = Path(__file__).parent.parent / 'ml' / 'models' / 'document_classifier.pth'
        
        if model_path.exists():
            try:
                import torch
                from .cnn_model import DocumentClassifier
                
                self.model = DocumentClassifier()
                self.model.load_state_dict(torch.load(model_path, map_location='cpu'))
                self.model.eval()
                self.model_loaded = True
                logger.info("CNN model loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load CNN model: {e}")
                self.model_loaded = False
        else:
            logger.info("No trained CNN model found - using quality-check mode")
    
    def analyze(self, file_path_or_bytes, expected_type=None):
        """
        Analyze a document image.
        
        Args:
            file_path_or_bytes: Path to image or bytes
            expected_type: Expected document type (optional)
        
        Returns:
            dict with analysis results
        """
        try:
            # Load image
            if isinstance(file_path_or_bytes, (str, Path)):
                image = Image.open(file_path_or_bytes)
            else:
                image = Image.open(io.BytesIO(file_path_or_bytes))
            
            # Convert to RGB if needed
            if image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Run quality checks
            quality_result = self._check_quality(image)
            
            # Run CNN classification if model available
            if self.model_loaded:
                classification = self._classify(image)
            else:
                classification = {
                    'predicted_type': expected_type or 'unknown',
                    'type_confidence': None,
                    'model_available': False
                }
            
            # Combine results
            return {
                'is_valid': quality_result['is_valid'],
                'quality_score': quality_result['quality_score'],
                'quality_issues': quality_result['issues'],
                'predicted_type': classification['predicted_type'],
                'type_confidence': classification.get('type_confidence'),
                'model_available': self.model_loaded,
                'analysis_mode': 'cnn' if self.model_loaded else 'quality_check'
            }
            
        except Exception as e:
            logger.error(f"Document analysis error: {str(e)}")
            return {
                'is_valid': False,
                'quality_score': 0,
                'quality_issues': ['Could not analyze image'],
                'error': str(e)
            }
    
    def _check_quality(self, image):
        """
        Check image quality.
        
        Checks:
        - Image size (minimum dimensions)
        - Blur detection (using Laplacian variance)
        - Brightness check
        """
        issues = []
        score = 100
        
        # Check dimensions
        width, height = image.size
        if width < MIN_IMAGE_SIZE[0] or height < MIN_IMAGE_SIZE[1]:
            issues.append(f'Image too small ({width}x{height}). Minimum: {MIN_IMAGE_SIZE[0]}x{MIN_IMAGE_SIZE[1]}')
            score -= 30
        
        # Check aspect ratio (too extreme = likely cropped badly)
        aspect = max(width, height) / min(width, height)
        if aspect > 5:
            issues.append('Unusual aspect ratio - image may be cropped incorrectly')
            score -= 15
        
        # Check blur using Laplacian variance (requires numpy/cv2)
        try:
            blur_score = self._check_blur(image)
            if blur_score < BLUR_THRESHOLD:
                issues.append(f'Image appears blurry (score: {blur_score:.0f})')
                score -= 25
        except ImportError:
            # cv2 not available, skip blur check
            pass
        
        # Check brightness
        brightness = self._check_brightness(image)
        if brightness < 40:
            issues.append('Image too dark')
            score -= 20
        elif brightness > 240:
            issues.append('Image too bright/overexposed')
            score -= 20
        
        score = max(0, min(100, score))
        
        return {
            'is_valid': len(issues) == 0 or score >= 50,
            'quality_score': score / 100,
            'issues': issues
        }
    
    def _check_blur(self, image):
        """Check blur using Laplacian variance"""
        try:
            import cv2
            import numpy as np
            
            # Convert PIL to cv2
            img_array = np.array(image)
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
            
            # Laplacian variance
            laplacian = cv2.Laplacian(gray, cv2.CV_64F)
            variance = laplacian.var()
            
            return variance
        except ImportError:
            return BLUR_THRESHOLD + 1  # Skip if cv2 not available
    
    def _check_brightness(self, image):
        """Check average brightness"""
        try:
            import numpy as np
            img_array = np.array(image)
            return np.mean(img_array)
        except ImportError:
            # Fallback without numpy
            pixels = list(image.getdata())
            avg = sum(sum(p[:3]) / 3 for p in pixels) / len(pixels)
            return avg
    
    def _classify(self, image):
        """Classify document type using CNN (if model loaded)"""
        if not self.model_loaded:
            return {'predicted_type': 'unknown', 'type_confidence': None}
        
        try:
            import torch
            from torchvision import transforms
            from .cnn_model import DOCUMENT_CLASSES  # Use single source of truth
            
            # Preprocess
            transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                                   std=[0.229, 0.224, 0.225])
            ])
            
            img_tensor = transform(image).unsqueeze(0)
            
            # Predict
            with torch.no_grad():
                outputs = self.model(img_tensor)
                probabilities = torch.softmax(outputs, dim=1)
                confidence, predicted = torch.max(probabilities, 1)
            
            # Get class name from centralized constant
            return {
                'predicted_type': DOCUMENT_CLASSES[predicted.item()],
                'type_confidence': confidence.item()
            }
            
        except Exception as e:
            logger.error(f"Classification error: {e}")
            return {'predicted_type': 'unknown', 'type_confidence': None}


# Singleton instance
_analyzer = None

def get_analyzer():
    """Get document analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = DocumentAnalyzer()
    return _analyzer


def analyze_document(file_path_or_bytes, expected_type=None):
    """Convenience function to analyze a document"""
    return get_analyzer().analyze(file_path_or_bytes, expected_type)

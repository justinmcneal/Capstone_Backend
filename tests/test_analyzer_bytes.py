from PIL import Image
import io

from documents.services.analyzer import analyze_document


def create_test_image_bytes(color=(255, 0, 0), size=(300, 300)):
    img = Image.new('RGB', size, color=color)
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    return buf.getvalue()


def test_analyze_bytes_basic():
    img_bytes = create_test_image_bytes()
    result = analyze_document(img_bytes, expected_type='other')
    assert isinstance(result, dict)
    assert 'is_valid' in result
    assert 'quality_score' in result

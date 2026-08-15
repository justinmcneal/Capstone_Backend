"""Versioned document-photo preprocessing shared by training and inference."""

import sys
import types

if "lzma" not in sys.modules or not hasattr(sys.modules.get("lzma"), "open"):
    try:
        import lzma  # noqa: F401
    except ImportError:
        m = types.ModuleType("lzma")
        setattr(m, "open", None)
        setattr(m, "LZMAError", Exception)
        sys.modules["lzma"] = m

from PIL import Image, ImageOps

PREPROCESSING_VERSION = "document-photo-letterbox-v2"
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class ResizeWithPadding:
    """Preserve document aspect ratio and letterbox to a deterministic square."""

    def __init__(self, size, fill=(255, 255, 255)):
        self.size = int(size)
        self.fill = fill

    def __call__(self, image):
        image = image.convert("RGB")
        image.thumbnail((self.size, self.size), Image.Resampling.LANCZOS)
        width, height = image.size
        left = (self.size - width) // 2
        top = (self.size - height) // 2
        return ImageOps.expand(
            image,
            border=(
                left,
                top,
                self.size - width - left,
                self.size - height - top,
            ),
            fill=self.fill,
        )


def build_inference_transform():
    """Return the immutable transform associated with the runtime policy."""
    from torchvision import transforms

    return transforms.Compose(
        [
            ResizeWithPadding(224),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )


def build_training_transform():
    """Apply conservative capture noise without mirroring or aspect distortion."""
    from torchvision import transforms

    return transforms.Compose(
        [
            ResizeWithPadding(256),
            transforms.RandomCrop(224),
            transforms.RandomRotation(5, fill=(255, 255, 255)),
            transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.1),
            transforms.RandomPerspective(distortion_scale=0.05, p=0.15),
            transforms.RandomApply(
                [transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 0.8))],
                p=0.15,
            ),
            transforms.ToTensor(),
            transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
        ]
    )

"""
MobileNetV2-based Document Classifier

This model uses transfer learning from MobileNetV2 to classify
document types for loan applications.
"""

import torch.nn as nn
from torchvision import models

# Document categories — MUST be alphabetical to match ImageFolder class ordering
DOCUMENT_CLASSES = [
    "business_permit",
    "business_photo",
    "income_proof",
    "invalid",
    "proof_of_address",
    "selfie_with_id",
    "valid_id",
]

NUM_CLASSES = len(DOCUMENT_CLASSES)


class DocumentClassifier(nn.Module):
    """
    MobileNetV2-based document classifier.

    Uses transfer learning for efficient training with limited data.
    """

    def __init__(self, num_classes=NUM_CLASSES, pretrained=True):
        super(DocumentClassifier, self).__init__()

        # Load pretrained MobileNetV2
        self.mobilenet = models.mobilenet_v2(
            weights=models.MobileNet_V2_Weights.DEFAULT if pretrained else None
        )

        # Replace classifier head with improved architecture
        num_features = self.mobilenet.classifier[1].in_features
        self.mobilenet.classifier = nn.Sequential(
            nn.Dropout(p=0.2),
            nn.Linear(num_features, 512),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Dropout(p=0.3),
            nn.Linear(512, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(256, num_classes),
        )

    def forward(self, x):
        return self.mobilenet(x)

    def freeze_backbone(self):
        """Freeze MobileNetV2 backbone for fine-tuning"""
        for param in self.mobilenet.features.parameters():
            param.requires_grad = False

    def unfreeze_backbone(self):
        """Unfreeze backbone for full training"""
        for param in self.mobilenet.features.parameters():
            param.requires_grad = True

    @classmethod
    def get_class_name(cls, index):
        """Get class name from index"""
        return (
            DOCUMENT_CLASSES[index] if 0 <= index < len(DOCUMENT_CLASSES) else "unknown"
        )

    @classmethod
    def get_class_index(cls, name):
        """Get index from class name"""
        return DOCUMENT_CLASSES.index(name) if name in DOCUMENT_CLASSES else -1


def create_model(pretrained=True):
    """Factory function to create the model"""
    return DocumentClassifier(pretrained=pretrained)

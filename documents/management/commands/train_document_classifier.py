"""
Django management command to train the document classifier.

Usage:
    python manage.py train_document_classifier
    python manage.py train_document_classifier --epochs 20
    python manage.py train_document_classifier --batch-size 16
"""
import os
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Train the document classifier CNN model'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--epochs',
            type=int,
            default=10,
            help='Number of training epochs (default: 10)'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=32,
            help='Batch size (default: 32)'
        )
        parser.add_argument(
            '--learning-rate',
            type=float,
            default=0.001,
            help='Learning rate (default: 0.001)'
        )
        parser.add_argument(
            '--fine-tune',
            action='store_true',
            help='Fine-tune the entire model (unfreeze backbone)'
        )
    
    def handle(self, *args, **options):
        # Check for PyTorch
        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim
            from torch.utils.data import DataLoader, random_split
            from torchvision import transforms, datasets
        except ImportError:
            self.stderr.write(self.style.ERROR(
                'PyTorch not installed. Run: pip install torch torchvision'
            ))
            return
        
        from documents.services.cnn_model import DocumentClassifier, DOCUMENT_CLASSES
        
        # Paths
        base_path = Path(settings.BASE_DIR) / 'documents' / 'ml'
        data_path = base_path / 'training_data'
        model_path = base_path / 'models' / 'document_classifier.pth'
        config_path = base_path / 'models' / 'model_config.json'
        
        # Check training data
        if not data_path.exists():
            self.stderr.write(self.style.ERROR(
                f'Training data folder not found: {data_path}'
            ))
            return
        
        # Count samples
        total_samples = 0
        class_counts = {}
        for class_dir in data_path.iterdir():
            if class_dir.is_dir() and class_dir.name in DOCUMENT_CLASSES:
                count = len(list(class_dir.glob('*.jpg'))) + \
                        len(list(class_dir.glob('*.jpeg'))) + \
                        len(list(class_dir.glob('*.png')))
                class_counts[class_dir.name] = count
                total_samples += count
        
        if total_samples < 50:
            self.stderr.write(self.style.WARNING(
                f'Only {total_samples} training samples found. '
                f'Recommended: at least 50 per class.\n'
                f'See: documents/ml/training_data/README.md for data sources.'
            ))
            if total_samples == 0:
                return
        
        self.stdout.write(f'Training samples: {total_samples}')
        for cls, count in class_counts.items():
            self.stdout.write(f'  {cls}: {count}')
        
        # Data transforms
        train_transforms = transforms.Compose([
            transforms.Resize((256, 256)),
            transforms.RandomCrop(224),
            transforms.RandomHorizontalFlip(),
            transforms.RandomRotation(10),
            transforms.ColorJitter(brightness=0.2, contrast=0.2),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        
        val_transforms = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
        ])
        
        # Load dataset
        try:
            full_dataset = datasets.ImageFolder(str(data_path), transform=train_transforms)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error loading dataset: {e}'))
            return
        
        # Split into train/val
        train_size = int(0.8 * len(full_dataset))
        val_size = len(full_dataset) - train_size
        train_dataset, val_dataset = random_split(full_dataset, [train_size, val_size])
        
        # Apply val transforms to validation set
        val_dataset.dataset.transform = val_transforms
        
        train_loader = DataLoader(
            train_dataset, 
            batch_size=options['batch_size'],
            shuffle=True,
            num_workers=0  # Set to 0 for compatibility
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=options['batch_size'],
            shuffle=False,
            num_workers=0
        )
        
        self.stdout.write(f'Train: {len(train_dataset)}, Val: {len(val_dataset)}')
        
        # Create model
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.stdout.write(f'Using device: {device}')
        
        model = DocumentClassifier(pretrained=True)
        
        if not options['fine_tune']:
            model.freeze_backbone()
            self.stdout.write('Backbone frozen (transfer learning mode)')
        else:
            self.stdout.write('Full fine-tuning mode')
        
        model = model.to(device)
        
        # Loss and optimizer
        criterion = nn.CrossEntropyLoss()
        optimizer = optim.Adam(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=options['learning_rate']
        )
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)
        
        # Training loop
        best_val_acc = 0.0
        epochs = options['epochs']
        
        self.stdout.write(f'\nStarting training for {epochs} epochs...\n')
        
        for epoch in range(epochs):
            # Train
            model.train()
            train_loss = 0.0
            train_correct = 0
            train_total = 0
            
            for inputs, labels in train_loader:
                inputs, labels = inputs.to(device), labels.to(device)
                
                optimizer.zero_grad()
                outputs = model(inputs)
                loss = criterion(outputs, labels)
                loss.backward()
                optimizer.step()
                
                train_loss += loss.item()
                _, predicted = torch.max(outputs, 1)
                train_total += labels.size(0)
                train_correct += (predicted == labels).sum().item()
            
            train_acc = 100 * train_correct / train_total
            
            # Validate
            model.eval()
            val_loss = 0.0
            val_correct = 0
            val_total = 0
            
            with torch.no_grad():
                for inputs, labels in val_loader:
                    inputs, labels = inputs.to(device), labels.to(device)
                    outputs = model(inputs)
                    loss = criterion(outputs, labels)
                    
                    val_loss += loss.item()
                    _, predicted = torch.max(outputs, 1)
                    val_total += labels.size(0)
                    val_correct += (predicted == labels).sum().item()
            
            val_acc = 100 * val_correct / val_total if val_total > 0 else 0
            
            self.stdout.write(
                f'Epoch {epoch+1}/{epochs} - '
                f'Train Loss: {train_loss/len(train_loader):.4f}, '
                f'Train Acc: {train_acc:.2f}% - '
                f'Val Loss: {val_loss/max(1,len(val_loader)):.4f}, '
                f'Val Acc: {val_acc:.2f}%'
            )
            
            # Save best model
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                torch.save(model.state_dict(), model_path)
                self.stdout.write(self.style.SUCCESS(f'  ✓ Model saved (best val acc: {val_acc:.2f}%)'))
            
            scheduler.step()
        
        # Save config
        config = {
            'classes': DOCUMENT_CLASSES,
            'num_classes': len(DOCUMENT_CLASSES),
            'best_val_accuracy': best_val_acc,
            'epochs_trained': epochs,
            'model_type': 'MobileNetV2',
            'input_size': [224, 224]
        }
        
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
        
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Training complete! Best validation accuracy: {best_val_acc:.2f}%\n'
            f'Model saved to: {model_path}\n'
            f'Config saved to: {config_path}'
        ))

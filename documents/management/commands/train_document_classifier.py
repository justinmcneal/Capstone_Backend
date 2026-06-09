"""
Django management command to train the document classifier.

Usage:
    python manage.py train_document_classifier
    python manage.py train_document_classifier --epochs 20
    python manage.py train_document_classifier --batch-size 16
"""

import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Train the document classifier CNN model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--epochs",
            type=int,
            default=10,
            help="Number of training epochs (default: 10)",
        )
        parser.add_argument(
            "--batch-size", type=int, default=32, help="Batch size (default: 32)"
        )
        parser.add_argument(
            "--learning-rate",
            type=float,
            default=0.001,
            help="Learning rate (default: 0.001)",
        )
        parser.add_argument(
            "--fine-tune",
            action="store_true",
            help="Fine-tune the entire model (unfreeze backbone)",
        )

    def handle(self, *args, **options):
        # Check for PyTorch
        try:
            import torch
            import torch.nn as nn
            import torch.optim as optim
            from torch.utils.data import DataLoader, Subset
            from torchvision import transforms, datasets
        except ImportError:
            self.stderr.write(
                self.style.ERROR(
                    "PyTorch not installed. Run: pip install torch torchvision"
                )
            )
            return

        from documents.services.cnn_model import DocumentClassifier, DOCUMENT_CLASSES

        # Paths
        base_path = Path(settings.BASE_DIR) / "documents" / "ml"
        data_path = base_path / "training_data"
        model_path = base_path / "models" / "document_classifier.pth"
        config_path = base_path / "models" / "model_config.json"

        # Check training data
        if not data_path.exists():
            self.stderr.write(
                self.style.ERROR(f"Training data folder not found: {data_path}")
            )
            return

        # Count samples
        total_samples = 0
        class_counts = {}
        for class_dir in data_path.iterdir():
            if class_dir.is_dir() and class_dir.name in DOCUMENT_CLASSES:
                count = (
                    len(list(class_dir.glob("*.jpg")))
                    + len(list(class_dir.glob("*.jpeg")))
                    + len(list(class_dir.glob("*.png")))
                )
                class_counts[class_dir.name] = count
                total_samples += count

        if total_samples < 50:
            self.stderr.write(
                self.style.WARNING(
                    f"Only {total_samples} training samples found. "
                    f"Recommended: at least 50 per class.\n"
                    f"See: documents/ml/training_data/README.md for data sources."
                )
            )
            if total_samples == 0:
                return

        self.stdout.write(f"Training samples: {total_samples}")
        for cls, count in class_counts.items():
            self.stdout.write(f"  {cls}: {count}")

        # Data transforms — strengthened augmentation
        train_transforms = transforms.Compose(
            [
                transforms.Resize((256, 256)),
                transforms.RandomCrop(224),
                transforms.RandomHorizontalFlip(),
                transforms.RandomRotation(15),
                transforms.ColorJitter(
                    brightness=0.3, contrast=0.3, saturation=0.2, hue=0.05
                ),
                transforms.RandomPerspective(distortion_scale=0.1, p=0.3),
                transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

        val_transforms = transforms.Compose(
            [
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )

        # Load dataset with SEPARATE transforms for train and val
        # (Using Subset to avoid shared transform reference bug)
        try:
            train_full = datasets.ImageFolder(
                str(data_path), transform=train_transforms
            )
            val_full = datasets.ImageFolder(str(data_path), transform=val_transforms)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error loading dataset: {e}"))
            return

        # Generate consistent random split indices
        import random

        indices = list(range(len(train_full)))
        random.seed(42)  # Reproducible split
        random.shuffle(indices)

        train_size = int(0.8 * len(indices))
        train_indices = indices[:train_size]
        val_indices = indices[train_size:]

        # Create separate subsets with their own transforms
        train_dataset = Subset(train_full, train_indices)
        val_dataset = Subset(val_full, val_indices)

        train_loader = DataLoader(
            train_dataset,
            batch_size=options["batch_size"],
            shuffle=True,
            num_workers=0,  # Set to 0 for compatibility
        )
        val_loader = DataLoader(
            val_dataset, batch_size=options["batch_size"], shuffle=False, num_workers=0
        )

        self.stdout.write(f"Train: {len(train_dataset)}, Val: {len(val_dataset)}")

        # Create model
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.stdout.write(f"Using device: {device}")

        model = DocumentClassifier(pretrained=True)

        if not options["fine_tune"]:
            model.freeze_backbone()
            self.stdout.write("Backbone frozen (transfer learning mode)")
        else:
            self.stdout.write("Full fine-tuning mode")

        model = model.to(device)

        # Loss and optimizer — use class-weighted loss to handle imbalance
        # Compute inverse-frequency weights from ImageFolder class counts
        class_sample_counts = [0] * len(train_full.classes)
        for _, label in train_full.samples:
            class_sample_counts[label] += 1

        class_weights = []
        for count in class_sample_counts:
            if count > 0:
                class_weights.append(total_samples / (len(train_full.classes) * count))
            else:
                class_weights.append(1.0)

        self.stdout.write("\nClass weights (inverse-frequency):")
        for i, cls_name in enumerate(train_full.classes):
            self.stdout.write(
                f"  {cls_name}: {class_weights[i]:.2f} ({class_sample_counts[i]} samples)"
            )

        weight_tensor = torch.FloatTensor(class_weights).to(device)
        criterion = nn.CrossEntropyLoss(weight=weight_tensor)
        optimizer = optim.Adam(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=options["learning_rate"],
        )
        scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.5)

        # Training loop with early stopping
        best_val_acc = 0.0
        epochs = options["epochs"]
        patience = 5  # Stop if no improvement for 5 epochs
        no_improve_count = 0

        # Track training history for plotting
        history = {
            "train_loss": [],
            "val_loss": [],
            "train_acc": [],
            "val_acc": [],
            "lr": [],
        }

        self.stdout.write(
            f"\nStarting training for {epochs} epochs (early stopping patience: {patience})...\n"
        )

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

            # Record history
            history["train_loss"].append(train_loss / len(train_loader))
            history["val_loss"].append(val_loss / max(1, len(val_loader)))
            history["train_acc"].append(train_acc)
            history["val_acc"].append(val_acc)
            history["lr"].append(optimizer.param_groups[0]["lr"])

            self.stdout.write(
                f"Epoch {epoch+1}/{epochs} - "
                f"Train Loss: {train_loss/len(train_loader):.4f}, "
                f"Train Acc: {train_acc:.2f}% - "
                f"Val Loss: {val_loss/max(1,len(val_loader)):.4f}, "
                f"Val Acc: {val_acc:.2f}%"
            )

            # Save best model with early stopping
            if val_acc > best_val_acc:
                best_val_acc = val_acc
                no_improve_count = 0
                torch.save(model.state_dict(), model_path)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✓ Model saved (best val acc: {val_acc:.2f}%)"
                    )
                )
            else:
                no_improve_count += 1
                if no_improve_count >= patience:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\n⚠️  Early stopping triggered (no improvement for {patience} epochs)"
                        )
                    )
                    break

            scheduler.step()

        # Save config — include ACTUAL class-to-idx mapping from ImageFolder
        config = {
            "classes": list(train_full.classes),
            "class_to_idx": train_full.class_to_idx,
            "num_classes": len(train_full.classes),
            "best_val_accuracy": best_val_acc,
            "epochs_trained": epoch + 1,
            "model_type": "MobileNetV2",
            "input_size": [224, 224],
            "history": history,
        }

        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        # Generate training curve plots
        reports_dir = base_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        self._plot_training_curves(history, reports_dir, class_counts)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Training complete! Best validation accuracy: {best_val_acc:.2f}%\n"
                f"Model saved to: {model_path}\n"
                f"Config saved to: {config_path}\n"
                f"Training charts saved to: {reports_dir}"
            )
        )

    def _plot_training_curves(self, history, reports_dir, class_counts):
        """Generate and save training diagnostic charts."""
        try:
            import matplotlib

            matplotlib.use("Agg")  # Non-interactive backend
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            self.stderr.write(
                self.style.WARNING(
                    "matplotlib not installed. Run: pip install matplotlib\n"
                    "Skipping training curve plots."
                )
            )
            return

        epochs_range = range(1, len(history["train_loss"]) + 1)

        # --- Figure 1: Training Curves (Loss + Accuracy + LR) ---
        fig, axes = plt.subplots(1, 3, figsize=(20, 6))
        fig.suptitle("CNN Training Diagnostics", fontsize=16, fontweight="bold", y=1.02)

        # Plot 1: Loss
        ax1 = axes[0]
        ax1.plot(
            epochs_range,
            history["train_loss"],
            "b-o",
            linewidth=2,
            markersize=6,
            label="Train Loss",
        )
        ax1.plot(
            epochs_range,
            history["val_loss"],
            "r-s",
            linewidth=2,
            markersize=6,
            label="Val Loss",
        )
        ax1.set_xlabel("Epoch", fontsize=12)
        ax1.set_ylabel("Loss", fontsize=12)
        ax1.set_title("Loss Curve", fontsize=14)
        ax1.legend(fontsize=11)
        ax1.grid(True, alpha=0.3)
        ax1.set_xticks(list(epochs_range))

        # Plot 2: Accuracy
        ax2 = axes[1]
        ax2.plot(
            epochs_range,
            history["train_acc"],
            "b-o",
            linewidth=2,
            markersize=6,
            label="Train Acc",
        )
        ax2.plot(
            epochs_range,
            history["val_acc"],
            "r-s",
            linewidth=2,
            markersize=6,
            label="Val Acc",
        )
        ax2.set_xlabel("Epoch", fontsize=12)
        ax2.set_ylabel("Accuracy (%)", fontsize=12)
        ax2.set_title("Accuracy Curve", fontsize=14)
        ax2.legend(fontsize=11)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim([0, 105])
        ax2.set_xticks(list(epochs_range))

        # Annotate best val accuracy
        best_epoch = np.argmax(history["val_acc"]) + 1
        best_acc = max(history["val_acc"])
        ax2.annotate(
            f"Best: {best_acc:.1f}%",
            xy=(best_epoch, best_acc),
            xytext=(best_epoch, best_acc - 12),
            arrowprops=dict(arrowstyle="->", color="green", lw=1.5),
            fontsize=10,
            color="green",
            fontweight="bold",
        )

        # Plot 3: Learning Rate
        ax3 = axes[2]
        ax3.plot(
            epochs_range,
            history["lr"],
            "g-^",
            linewidth=2,
            markersize=6,
            label="Learning Rate",
        )
        ax3.set_xlabel("Epoch", fontsize=12)
        ax3.set_ylabel("Learning Rate", fontsize=12)
        ax3.set_title("Learning Rate Schedule", fontsize=14)
        ax3.legend(fontsize=11)
        ax3.grid(True, alpha=0.3)
        ax3.ticklabel_format(style="scientific", axis="y", scilimits=(0, 0))
        ax3.set_xticks(list(epochs_range))

        plt.tight_layout()
        fig.savefig(reports_dir / "training_curves.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        self.stdout.write(f'\n📊 Saved: {reports_dir / "training_curves.png"}')

        # --- Figure 2: Training Data Distribution ---
        fig2, ax4 = plt.subplots(figsize=(10, 6))
        classes = list(class_counts.keys())
        counts = list(class_counts.values())
        colors = plt.cm.Set3(np.linspace(0, 1, len(classes)))

        bars = ax4.bar(classes, counts, color=colors, edgecolor="black", linewidth=0.8)
        ax4.set_xlabel("Document Class", fontsize=12)
        ax4.set_ylabel("Number of Images", fontsize=12)
        ax4.set_title("Training Data Distribution", fontsize=14, fontweight="bold")
        ax4.tick_params(axis="x", rotation=30)
        ax4.grid(axis="y", alpha=0.3)

        # Add count labels on bars
        for bar, count in zip(bars, counts):
            ax4.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                str(count),
                ha="center",
                va="bottom",
                fontsize=11,
                fontweight="bold",
            )

        # Add imbalance warning line
        avg_count = sum(counts) / len(counts)
        ax4.axhline(
            y=avg_count,
            color="red",
            linestyle="--",
            linewidth=1.5,
            alpha=0.7,
            label=f"Average: {avg_count:.0f}",
        )
        ax4.legend(fontsize=11)

        plt.tight_layout()
        fig2.savefig(
            reports_dir / "data_distribution.png", dpi=150, bbox_inches="tight"
        )
        plt.close(fig2)
        self.stdout.write(f'📊 Saved: {reports_dir / "data_distribution.png"}')

        # --- Figure 3: Overfitting Gap ---
        fig3, ax5 = plt.subplots(figsize=(10, 6))
        gap = [t - v for t, v in zip(history["train_acc"], history["val_acc"])]

        bar_colors = ["green" if g < 10 else "orange" if g < 20 else "red" for g in gap]
        ax5.bar(epochs_range, gap, color=bar_colors, edgecolor="black", linewidth=0.8)
        ax5.axhline(
            y=10,
            color="orange",
            linestyle="--",
            linewidth=1.5,
            label="Warning (10%)",
            alpha=0.7,
        )
        ax5.axhline(
            y=20,
            color="red",
            linestyle="--",
            linewidth=1.5,
            label="Overfitting (20%)",
            alpha=0.7,
        )
        ax5.set_xlabel("Epoch", fontsize=12)
        ax5.set_ylabel("Train Acc − Val Acc (%)", fontsize=12)
        ax5.set_title("Overfitting Gap", fontsize=14, fontweight="bold")
        ax5.legend(fontsize=11)
        ax5.grid(axis="y", alpha=0.3)
        ax5.set_xticks(list(epochs_range))

        plt.tight_layout()
        fig3.savefig(reports_dir / "overfitting_gap.png", dpi=150, bbox_inches="tight")
        plt.close(fig3)
        self.stdout.write(f'📊 Saved: {reports_dir / "overfitting_gap.png"}')

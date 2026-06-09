terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

resource "aws_kms_key" "documents_kms" {
  description             = "KMS key for document storage"
  deletion_window_in_days = 30
}

resource "aws_s3_bucket" "documents_bucket" {
  bucket = var.bucket_name
  acl    = "private"

  versioning {
    enabled = true
  }

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm     = "aws:kms"
        kms_master_key_id = aws_kms_key.documents_kms.key_id
      }
    }
  }

  lifecycle_rule {
    id      = "keep-versions"
    enabled = true
    noncurrent_version_transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}

resource "aws_kms_alias" "documents_kms_alias" {
  name          = "alias/documents_kms"
  target_key_id = aws_kms_key.documents_kms.key_id
}

output "bucket_name" {
  value = aws_s3_bucket.documents_bucket.bucket
}

output "kms_key_arn" {
  value = aws_kms_key.documents_kms.arn
}

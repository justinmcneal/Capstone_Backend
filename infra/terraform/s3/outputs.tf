output "bucket_arn" {
  value = aws_s3_bucket.documents_bucket.arn
}

output "kms_key_id" {
  value = aws_kms_key.documents_kms.key_id
}

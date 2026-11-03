output "artifacts_bucket_arn" {
  description = "ARN of the artifacts bucket."
  value       = aws_s3_bucket.artifacts.arn
}

output "app_role_arn" {
  description = "IAM role assumed by the orders-api pods (EKS Pod Identity)."
  value       = aws_iam_role.app.arn
}

output "orders_db_endpoint" {
  description = "Connection endpoint of the orders database."
  value       = aws_db_instance.orders.endpoint
}

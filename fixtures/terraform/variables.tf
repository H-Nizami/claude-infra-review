variable "region" {
  description = "AWS region. Data residency policy allows EU regions only (see fixtures/POLICY.md)."
  type        = string
  default     = "eu-central-1"

  validation {
    condition     = contains(["eu-central-1", "eu-west-1"], var.region)
    error_message = "Region must be eu-central-1 or eu-west-1 (data residency policy)."
  }
}

variable "vpc_id" {
  description = "ID of the VPC that hosts the app security group."
  type        = string
  default     = "vpc-00000000000000000"
}

variable "db_subnet_group_name" {
  description = "Existing private DB subnet group for the orders database."
  type        = string
  default     = "orders-private"
}

variable "allowed_cidr" {
  description = "Internal CIDR allowed to reach the app on 443."
  type        = string
  default     = "10.0.0.0/8"
}

variable "kms_deletion_window" {
  description = "Days before a scheduled KMS key deletion takes effect."
  type        = number
  default     = 30
}

variable "artifacts_bucket_name" {
  description = "Name of the artifacts bucket."
  type        = string
  default     = "example-com-orders-artifacts"
}

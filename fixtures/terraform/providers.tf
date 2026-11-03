provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "claude-infra-review"
      Owner   = "platform"
    }
  }
}

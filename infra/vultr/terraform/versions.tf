terraform {
  required_version = ">= 1.6"
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "~> 2.33"
    }
  }
  # State lives in Vultr Object Storage (S3-compatible). Bucket/keys are passed at init:
  #   terraform init -backend-config=backend.hcl   (see backend.hcl.example)
  backend "s3" {
    key                         = "zentry/terraform.tfstate"
    region                      = "us-east-1" # ignored by Vultr; required by the S3 backend
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
    use_path_style              = true
  }
}

provider "vultr" {
  # reads VULTR_API_KEY from the environment
  rate_limit  = 700
  retry_limit = 3
}

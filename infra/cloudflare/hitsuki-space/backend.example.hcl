bucket = "3dgen-runs"
key    = "terraform/hitsuki-space/terraform.tfstate"
region = "auto"

skip_credentials_validation = true
skip_metadata_api_check     = true
skip_region_validation      = true
skip_requesting_account_id  = true
skip_s3_checksum            = true
use_path_style              = true

endpoints = {
  s3 = "https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com"
}

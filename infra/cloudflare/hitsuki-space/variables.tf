variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for hitsuki.space. Pass with TF_VAR_cloudflare_zone_id."
  type        = string
  nullable    = false

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.cloudflare_zone_id))
    error_message = "cloudflare_zone_id must be the 32-character lowercase hexadecimal ID for hitsuki.space."
  }
}

locals {
  zone_name       = "hitsuki.space"
  worker_hostname = "3dgen.hitsuki.space"

  # Cloudflare's 34-code ip.src.is_in_european_union set + GB + KR. This
  # includes EU regions with separate ISO codes. Keep it aligned with the
  # Worker-side deny list in web/src/worker.ts.
  hunyuan_blocked_countries = [
    "AT", "AX", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GF",
    "GP", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MF", "MQ", "MT", "NL",
    "PL", "PT", "RE", "RO", "SE", "SI", "SK", "YT",
    "GB", "KR",
  ]

  hunyuan_country_literals = join(" ", [
    for country in local.hunyuan_blocked_countries : "\"${country}\""
  ])

  hunyuan_waf_expression = format(
    "(lower(http.host) eq \"%s\" and starts_with(http.request.uri.path, \"/run-assets/hunyuan3d-21/\") and ip.src.country in {%s})",
    local.worker_hostname,
    local.hunyuan_country_literals,
  )

  apex_redirect_expression = format("(lower(http.host) eq \"%s\")", local.zone_name)
  apex_target_expression   = format("concat(\"https://%s\", http.request.uri.path)", local.worker_hostname)
}

# A proxied placeholder is required so requests for the apex reach the Ruleset
# Engine. 192.0.2.0 is Cloudflare's documented originless-redirect address.
resource "cloudflare_dns_record" "apex_redirect" {
  zone_id = var.cloudflare_zone_id
  name    = local.zone_name
  type    = "A"
  content = "192.0.2.0"
  proxied = true
  ttl     = 1
  comment = "Originless apex record for the hitsuki.space redirect ruleset"
}

resource "cloudflare_ruleset" "hunyuan_geo_block" {
  zone_id     = var.cloudflare_zone_id
  name        = "3dgen Hunyuan geo restriction"
  description = "Phase entrypoint for license-based Hunyuan3D 2.1 asset blocking"
  kind        = "zone"
  phase       = "http_request_firewall_custom"

  rules = [{
    ref         = "block_hunyuan3d_21_eu_gb_kr"
    description = "Block Hunyuan3D 2.1 assets in EU territory, GB, and KR"
    expression  = local.hunyuan_waf_expression
    action      = "block"
    enabled     = true
  }]
}

resource "cloudflare_ruleset" "apex_redirect" {
  zone_id     = var.cloudflare_zone_id
  name        = "hitsuki.space apex redirect"
  description = "Phase entrypoint redirecting the apex to the 3dgen Worker Custom Domain"
  kind        = "zone"
  phase       = "http_request_dynamic_redirect"

  rules = [{
    ref         = "redirect_hitsuki_space_to_3dgen"
    description = "Redirect hitsuki.space to 3dgen.hitsuki.space"
    expression  = local.apex_redirect_expression
    action      = "redirect"
    enabled     = true
    action_parameters = {
      from_value = {
        status_code = 301
        target_url = {
          expression = local.apex_target_expression
        }
        preserve_query_string = true
      }
    }
  }]
}

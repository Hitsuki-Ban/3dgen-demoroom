mock_provider "cloudflare" {}

run "domain_contract" {
  command = plan

  variables {
    cloudflare_zone_id = "0123456789abcdef0123456789abcdef"
  }

  assert {
    condition = (
      cloudflare_dns_record.apex_redirect.name == "hitsuki.space" &&
      cloudflare_dns_record.apex_redirect.content == "192.0.2.0" &&
      cloudflare_dns_record.apex_redirect.proxied &&
      cloudflare_dns_record.apex_redirect.ttl == 1
    )
    error_message = "The apex must remain a proxied 192.0.2.0 originless redirect record with automatic TTL."
  }

  assert {
    condition = (
      length(local.hunyuan_blocked_countries) == 36 &&
      length(toset(local.hunyuan_blocked_countries)) == 36 &&
      toset(local.hunyuan_blocked_countries) == toset([
        "AT", "AX", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GF",
        "GP", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MF", "MQ", "MT", "NL",
        "PL", "PT", "RE", "RO", "SE", "SI", "SK", "YT",
        "GB", "KR",
      ]) &&
      alltrue([
        for country in local.hunyuan_blocked_countries :
        strcontains(local.hunyuan_waf_expression, "\"${country}\"")
      ])
    )
    error_message = "The Hunyuan WAF country set must contain Cloudflare's 34 EU codes plus GB and KR."
  }

  assert {
    condition = (
      cloudflare_ruleset.hunyuan_geo_block.phase == "http_request_firewall_custom" &&
      cloudflare_ruleset.hunyuan_geo_block.kind == "zone" &&
      cloudflare_ruleset.hunyuan_geo_block.rules[0].ref == "block_hunyuan3d_21_eu_gb_kr" &&
      cloudflare_ruleset.hunyuan_geo_block.rules[0].action == "block" &&
      cloudflare_ruleset.hunyuan_geo_block.rules[0].expression == local.hunyuan_waf_expression &&
      strcontains(local.hunyuan_waf_expression, "lower(http.host) eq \"3dgen.hitsuki.space\"") &&
      strcontains(local.hunyuan_waf_expression, "starts_with(http.request.uri.path, \"/run-assets/hunyuan3d-21/\")")
    )
    error_message = "The WAF entrypoint must block the exact Custom Domain and Hunyuan asset prefix."
  }

  assert {
    condition = (
      cloudflare_ruleset.apex_redirect.phase == "http_request_dynamic_redirect" &&
      cloudflare_ruleset.apex_redirect.kind == "zone" &&
      cloudflare_ruleset.apex_redirect.rules[0].ref == "redirect_hitsuki_space_to_3dgen" &&
      cloudflare_ruleset.apex_redirect.rules[0].action == "redirect" &&
      cloudflare_ruleset.apex_redirect.rules[0].action_parameters.from_value.status_code == 301 &&
      cloudflare_ruleset.apex_redirect.rules[0].action_parameters.from_value.target_url.expression == "concat(\"https://3dgen.hitsuki.space\", http.request.uri.path)" &&
      cloudflare_ruleset.apex_redirect.rules[0].action_parameters.from_value.preserve_query_string
    )
    error_message = "The apex redirect must be a stable 301 that preserves the request path and query string."
  }
}

# `hitsuki.space` Cloudflare zone configuration

This directory is the source of truth for the zone-level pieces of Issue #67:

- proxied, originless apex DNS record;
- Hunyuan3D 2.1 WAF block for Cloudflare's 34-code EU set plus GB and KR;
- apex-to-Worker Single Redirect.

The Worker Custom Domain itself is declared in `web/wrangler.jsonc`. **Do not apply or deploy either configuration until the `hitsuki.space` zone is Active.**

## Pinned tools and credentials

- Terraform `1.15.7` (exact)
- `cloudflare/cloudflare` provider `5.21.1` (exact; lock file is committed)
- `CLOUDFLARE_API_TOKEN`: Zone Read, DNS Write, Zone WAF Write, Dynamic URL Redirects Write; its resource scope must include `hitsuki.space`
- `TF_VAR_cloudflare_zone_id`: the 32-character ID for `hitsuki.space`; there is no default
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`: R2 credentials scoped Read & Write to `3dgen-runs`, used only for remote Terraform state

Copy `backend.example.hcl` to ignored `backend.hcl` and replace `<CLOUDFLARE_ACCOUNT_ID>` with the exact account ID. Do not put credentials in either file. The state key is outside `site-data/`, so the Worker cannot serve it through `/run-assets/*`.

## Mandatory preflight: phase ownership

Cloudflare's provider treats each zone phase entrypoint ruleset as a complete resource. An apply with an incomplete `rules` list can remove rules that are not in this configuration.

Before the first apply, query all three existing objects with the same API token:

```text
GET /client/v4/zones/$ZONE_ID/rulesets/phases/http_request_firewall_custom/entrypoint
GET /client/v4/zones/$ZONE_ID/rulesets/phases/http_request_dynamic_redirect/entrypoint
GET /client/v4/zones/$ZONE_ID/dns_records?type=A&name=hitsuki.space
```

Proceed as a first creation only when both ruleset requests return Cloudflare's documented `404 Not Found` and the DNS query returns an empty result. Any authentication error, unexpected response, existing entrypoint, or existing apex record is a hard stop.

For an existing entrypoint, import its complete ruleset before planning:

```text
terraform import cloudflare_ruleset.hunyuan_geo_block "zones/$ZONE_ID/$WAF_RULESET_ID"
terraform import cloudflare_ruleset.apex_redirect "zones/$ZONE_ID/$REDIRECT_RULESET_ID"
terraform import cloudflare_dns_record.apex_redirect "$ZONE_ID/$DNS_RECORD_ID"
```

Then represent **every** existing rule in the corresponding Terraform resource before applying, and reconcile an imported apex record in the same way. Never delete or silently replace pre-existing zone configuration to make this plan pass.

## Validate and apply

Formatting, provider-schema validation, and mock-provider tests do not need Cloudflare or R2 credentials:

```powershell
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
terraform test
```

After the zone is Active, credentials are present, the mandatory preflight is clean, and the plan has been reviewed:

```powershell
terraform init -backend-config=backend.hcl
terraform plan -out=hitsuki-space.tfplan
terraform apply hitsuki-space.tfplan
```

Deploy `web/wrangler.jsonc` only after the zone resources succeed. Cloudflare then creates the `3dgen.hitsuki.space` DNS record and certificate for the Worker Custom Domain.

## References (verified 2026-07-12)

- [Cloudflare WAF custom rules with Terraform](https://developers.cloudflare.com/terraform/additional-configurations/waf-custom-rules/)
- [Cloudflare `ip.src.is_in_european_union` country list](https://developers.cloudflare.com/ruleset-engine/rules-language/fields/reference/ip.src.is_in_european_union/)
- [Cloudflare Single Redirects](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/)
- [Cloudflare Custom Domains and originless redirect DNS](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
- [Cloudflare R2 remote backend](https://developers.cloudflare.com/terraform/advanced-topics/remote-backend/)
- [Cloudflare provider 5.21.1](https://registry.terraform.io/providers/cloudflare/cloudflare/5.21.1)

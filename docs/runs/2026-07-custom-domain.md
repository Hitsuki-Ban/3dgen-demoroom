# `3dgen.hitsuki.space` Custom Domain 導入記録

- Issue: [#67](https://github.com/Hitsuki-Ban/3dgen-demoroom/issues/67)
- 確認日: 2026-07-12 (JST)
- Cloudflare account: 既存の `3dgen-demoroom` / `3dgen-runs` と同一 account
- 対象 zone / hostname: `hitsuki.space` / `3dgen.hitsuki.space`

## Phase 1 — Zone 作成と委譲

Cloudflare API 上の作成時刻 2026-07-12 03:49:54 JST に Cloudflare Free Zone を作成した。Cloudflare quick scan は 0 records で、別途行った公開 DNS の照合でも apex の A / AAAA / CNAME / MX / TXT / CAA は空、`3dgen.hitsuki.space` は NXDOMAIN だった。公開 DS も空で、RDAP の `delegationSigned` は false だった。

| 項目 | 値 |
|---|---|
| Zone ID | `b7dc9d85ee385874274b2b4fefe32ce2` |
| Zone status | `Active` (2026-07-12 12:22:11 JST) |
| 旧 nameservers | `berger.dnspod.net`, `geraldine.dnspod.net` |
| Cloudflare nameservers | `braelyn.ns.cloudflare.com`, `vern.ns.cloudflare.com` |
| 旧 NS TTL | 86400 seconds |
| Scan review | 0 records; 全レコード空を確認して activation へ進行 |

Owner には TencentCloud / DNSPod で DNSSEC が無効であることを確認し、旧 NS 2 本を Cloudflare NS 2 本だけに置換するよう [Issue コメント](https://github.com/Hitsuki-Ban/3dgen-demoroom/issues/67#issuecomment-4948366411)で依頼した。TencentCloud の更新後、registry RDAP は 12:16:55 JST に Cloudflare NS 2 本へ更新され、12:19 JST には `.space` の registry authoritative nameservers 2 本、12:21 JST には 1.1.1.1 が新委譲を返した。公開 DS は終始空だった。Cloudflare は 12:22:11 JST に zone を `Active` とした。

### Account-side read-only preflight (2026-07-12 04:27 JST)

Cloudflare API で zone と Phase 2 の競合候補を再確認した。zone は `pending` / Free plan、`activated_on` は null、original nameservers は DNSPod の 2 本のままだった。

| Check | Result |
|---|---|
| Zone DNS records | 0 records |
| DNS scan review | 0 records |
| Worker Custom Domain (`3dgen.hitsuki.space`) | 0 domains |
| `http_request_firewall_custom` entrypoint | 現在の API token では `request is not authorized` |
| `http_request_dynamic_redirect` entrypoint | 現在の API token では `request is not authorized` |

Ruleset 2 項目は「存在しない」とは判定していない。Phase 2 の apply 直前に `Zone WAF Read` と `Dynamic URL Redirects Read` を含む token で entrypoint を再照合し、既存 ruleset があれば import または所有範囲を合意してから進める。DNS / scan / Custom Domain の 0 件は同じ API session で正常な 200 response として取得した。

### Active 後の first-creation preflight (2026-07-12 12:23 JST)

Active 後に zone-level ruleset 一覧を API で取得した。存在したのは Cloudflare managed の sanitize、Free managed WAF、L7 DDoS ruleset の 3 件だけで、`http_request_firewall_custom` / `http_request_dynamic_redirect` の zone entrypoint はなく、zone DNS records と `3dgen.hitsuki.space` Worker Custom Domain も 0 件だった。したがって import 対象はなく、Terraform の first creation として進められる。

## Phase 2 — Terraform / Worker deployment

2026-07-12 12:58 JST に、同じ zone-scoped token で mandatory preflight を再実行した。WAF / Dynamic Redirect entrypoint は双方 Cloudflare error 10003 の 404、apex A query は 200 / 0 records だった。

Terraform plan は 3 add / 0 change / 0 destroy だけを含み、保存した plan を apply した。R2 backend への state write 後の refresh plan は `No changes` だった。

| Resource | ID / result |
|---|---|
| Proxied apex A | `13d5fd76297bd86f5f3e2bc0c53c8b3f`; `hitsuki.space -> 192.0.2.0` |
| Hunyuan WAF ruleset | `6d21e7af767f46dd89a9ae33ebb3bc75`; version 1; 1 enabled rule / 36 codes |
| Apex redirect ruleset | `7522cf5c7d9b48b9a74bd9725d026979`; version 1; 301 / path + query preserved |
| Remote state | `s3://3dgen-runs/terraform/hitsuki-space/terraform.tfstate`; 11,462 bytes |

Wrangler `4.107.0` で production build を deploy し、Custom Domain と read-only AAAA record、certificate が自動作成された。最初の deploy で、Wrangler 4 は未指定の `workers_dev` を無効化することが判明した。Issue の Phase 3 で Fable が移行方針を決めるまで既存 URL を維持する要件に従い、`workers_dev: true` を source of truth に追加して即時再 deploy した。最終 version は `3665aa5a-2613-4e1a-951f-4013dd7221ad` で、以下の 2 triggers を持つ。

- `https://3dgen-demoroom.houtei-ban.workers.dev`
- `3dgen.hitsuki.space` Custom Domain (domain ID `5c288b3fb9ddcc30dcdac7f347e724cb6f7c3a98`)

### Live verification (2026-07-12 13:00–13:04 JST)

| Check | Result |
|---|---|
| `https://3dgen.hitsuki.space/` | 200, valid TLS, production HTML |
| existing workers.dev root | 200; Custom Domain と同じ JS / CSS bundle hash |
| `http://hitsuki.space/a/b?x=1&y=two` | 301 → `https://3dgen.hitsuki.space/a/b?x=1&y=two` |
| `https://hitsuki.space/a/b?x=1&y=two` | same 301 Location |
| unrestricted TripoSR HEAD | 200, `model/gltf-binary`, exact length / ETag |
| Hunyuan HEAD from local JP | 200, `model/gltf-binary`, exact length / ETag |

Globalping の実 HTTP HEAD probes を使い、同じ既存 Hunyuan GLB を JP / DE / GB / KR から照合した。

- WAF layer / Custom Domain ([measurement `2jroSWbEzXg5DAmXV00020kFv`](https://globalping.io?measurement=2jroSWbEzXg5DAmXV00020kFv)): JP 200、DE / GB / KR は Cloudflare 403。
- Worker layer / workers.dev ([measurement `291J5E15pcr8zh06J00020kFv`](https://globalping.io?measurement=291J5E15pcr8zh06J00020kFv)): JP 200、DE / GB / KR は 451 `Unavailable For Legal Reasons` + `Cache-Control: no-store`。

WAF expression は Custom Domain host だけを対象とするため、workers.dev probe は WAF を経由せず Worker の二層目を独立に検査する。両 measurement は各 country の実 probe location と Cloudflare `cf-ray` を記録している。

### Repository-side validation (2026-07-12)

- HashiCorp 公式 archive と SHA-256 一覧から Terraform `1.15.7` を取得し、checksum 一致を確認した(システム PATH には追加していない)。
- Cloudflare provider `5.21.1` を固定し、`terraform init -backend=false` / `terraform validate` が成功した。
- mock provider の `terraform test -verbose` は 1/1 pass。plan は apex DNS、WAF ruleset、redirect ruleset の 3 add で、WAF の 36 country codes、host / path、redirect の 301 / path / query 契約を検査した。
- Worker と Terraform の country set は双方 36 unique codes で、差分 0 を機械比較した。
- R2 の canonical `site-data/` から 274 success / 1 expected failure の完全な 11 models x 25 tasks snapshot を再構成し、production manifest validator と Vite build を通した。
- Wrangler `4.107.0` の `deploy --dry-run` は、上記 production build の 31 assets、R2 / Static Assets bindings、Custom Domain route を検証して成功した。その同じ build を live deploy した。
- R2 remote backend は既存の bucket-scoped credentials で初期化し、first apply 後に state object と 3 resources、続く no-change plan を確認した。
- Terraform は `hitsuki.space` だけに限定した Zone Read / DNS Edit / Zone WAF Edit / Single Redirect Edit token を使った。live resources を state 外で作成する API fallback は使用していない。

当初 Issue と設計稿は「EU27 + GB + KR = 29 codes」としていたが、Fable review 後に一次資料を再確認した。Tencent license の除外対象は EU **territory** であり、Cloudflare が `ip.src.is_in_european_union=true` と判定する公式一覧は 34 codes である。Free plan ではこの boolean field を使えないため、同じ 34 codes (`AX/GF/GP/MF/MQ/RE/YT` を含む)に GB と KR を足した 36 codes を WAF と Worker の双方で列挙する。これにより Business 以上の組み込み EU 判定と同じ地理範囲になる。

## Source of truth と権限

- Worker Custom Domain: `web/wrangler.jsonc`
- Zone DNS / WAF / Single Redirect: `infra/cloudflare/hitsuki-space/`
- Worker の geo 二層目: `web/src/worker.ts`

Terraform token には Zone Read、DNS Write、Zone WAF Write、Dynamic URL Redirects Write が必要で、resource scope は `hitsuki.space` だけに限定する。Wrangler は別の OAuth session の Workers Scripts / Routes Write を使う。Terraform state 用 R2 credentials も Cloudflare API token と分離し、環境変数だけで渡す。

## 参照(2026-07-12 確認)

- [Cloudflare full setup](https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/)
- [Cloudflare API token permissions](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)
- [Workers Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/)
- [WAF custom rules using Terraform](https://developers.cloudflare.com/terraform/additional-configurations/waf-custom-rules/)
- [Cloudflare `ip.src.is_in_european_union` country list](https://developers.cloudflare.com/ruleset-engine/rules-language/fields/reference/ip.src.is_in_european_union/)
- [Single Redirects](https://developers.cloudflare.com/rules/url-forwarding/single-redirects/)
- [Terraform R2 remote backend](https://developers.cloudflare.com/terraform/advanced-topics/remote-backend/)
- [TencentCloud: DNS サーバーの変更](https://cloud.tencent.com/document/product/302/5518)

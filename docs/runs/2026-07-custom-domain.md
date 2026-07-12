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

## Phase 2 — Active 後に実行

Zone は `Active` になった。以下は順番を維持し、Terraform apply が成功するまで Worker を deploy しない。

1. `Zone WAF Read` と `Dynamic URL Redirects Read` を含む token で `infra/cloudflare/hitsuki-space/` の preflight を実行し、既存 phase entrypoint がないことを確認してから、Terraform で proxied apex DNS、Hunyuan geo WAF、apex redirect を適用する。
2. `web/wrangler.jsonc` の Custom Domain route を含めて `wrangler deploy` し、Cloudflare が `3dgen.hitsuki.space` の DNS と証明書を作成したことを確認する。
3. `https://3dgen.hitsuki.space/` が 200、`http(s)://hitsuki.space/<path>?<query>` が path / query を保った 301 になることを確認する。
4. Cloudflare Trace と外部 probe で、JP から Hunyuan asset が 200、DE / GB / KR から `/run-assets/hunyuan3d-21/*` が WAF Block になることを確認する。Worker の二層目は対象国または国不明時に 451 を返す。

### Repository-side validation (2026-07-12)

- HashiCorp 公式 archive と SHA-256 一覧から Terraform `1.15.7` を取得し、checksum 一致を確認した(システム PATH には追加していない)。
- Cloudflare provider `5.21.1` を固定し、`terraform init -backend=false` / `terraform validate` が成功した。
- mock provider の `terraform test -verbose` は 1/1 pass。plan は apex DNS、WAF ruleset、redirect ruleset の 3 add で、WAF の 36 country codes、host / path、redirect の 301 / path / query 契約を検査した。
- Worker と Terraform の country set は双方 36 unique codes で、差分 0 を機械比較した。
- R2 の canonical `site-data/` から 274 success / 1 expected failure の完全な 11 models x 25 tasks snapshot を再構成し、production manifest validator と Vite build を通した。
- Wrangler `4.107.0` の `deploy --dry-run` は、上記 production build の 31 assets、R2 / Static Assets bindings、Custom Domain route を検証して成功した。実際の Custom Domain 作成はまだ行っていない。
- R2 remote backend は既存の bucket-scoped credentials で初期化でき、対象 key に既存 Terraform state がないことを確認した。
- Terraform apply は `hitsuki.space` だけに限定した Zone Read / DNS Edit / Zone WAF Edit / Dynamic URL Redirects Edit token がローカル環境にないため未実行。live resources を state 外で作成する API fallback は使用しない。

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

# Issue #85 cell orientation alignment run

- 実施日: 2026-07-13
- local renderer: RTX 4070 Ti / ANGLE D3D11
- R2 prefix: `s3://3dgen-runs/site-data`

## Result

Canonical inventory は 11 models x 25 tasks = 275 cells で、実体は 274 success と
`partcrafter/chrome-espresso-machine` の 1 expected failure である。
`web/src/data/orientation-fixes.json` は全 275 key を持ち、274 件を `fixed`、expected failure を
`excluded` として記録した。中心化 framing で候補を再採点した最終内訳は auto provenance
116 件、目視選択した manual provenance 158 件である。

`web/src/data/orientation-selected-evidence.json` は全 275 cell の selected rank、rotation、score、
source GLB identity、reference mask hash と provenance を保持する。gitignored report を必要とせず、
clean checkout でこの ledger だけから `orientation-fixes.json` を決定的に再生成できる。

全 274 success cell を新しい orientation-aware fingerprint で再レンダリングし、R2 への
conditional PUT、アップロード後の GET、WebP decode、source identity、SHA-256 を検証した。

- render fingerprint: `8b10de947a28c4ed13af9eeaec1d76017528739a2ba4d486dd239cae605a906a`
- orientation registry SHA-256: `effaf8866ea33b3a7d603fc828e2b7376615a062bac5bbc11cbbcb0427a72c4c`
- selected evidence SHA-256: `14d8ec533124fdea4137527c16aeeb20e9437d8bff38cf59210285cf0c012ebe`
- full search report SHA-256 (ledger binding): `5b02225ea761c89819a3977e63ddc880b14cf2d7f967a64f53d2498582de1c8a`
- publish: 274 rendered / 0 failed
- independent check: 274 fresh / 0 stale / 0 failed
- published thumbnail download audit: 274/274 response body SHA-256 matched the R2 check report
- final published contact sheets: 25/25 generated and visually reviewed

25 sheets の縮小 overview は
[2026-07-orientation-alignment-contact-sheets.webp](./2026-07-orientation-alignment-contact-sheets.webp)
に保存した。各 sheet は reference + canonical model order 11 件の 4 x 3 panel である。

ローカルの再現 evidence は gitignored `outputs/issue-85/` に保存した。

- `search-centered-report.json`: 全候補 ranking を含む 274-cell centered candidate search
- `thumbnail-centered-publish-report.json`: 最終 R2 publication report
- `thumbnail-centered-check-report.json`: 最終 independent fresh audit
- `published-contact-sheets/`: 公開 URL から SHA-256 検証後に組み直した最終 25 sheets

## Visual review boundary

公開 contact sheets では課題内の principal facing direction が揃っていることを全 25 課題で
確認した。一方、次の生成物は source geometry 自体が断片化、複数物体化、または欠損しており、
orientation だけでは修復できない。best available direction を選び、registry の manual reason に
geometry limitation を明記した。

- `3dtopia-xl/medieval-longsword`
- `3dtopia-xl/old-oak-tree`
- `partcrafter/medieval-longsword`
- `partcrafter/plasma-rifle`
- `partcrafter/potted-monstera`
- `partcrafter/stylized-hover-bike`
- `partcrafter/victorian-street-lamp`

## Deployment handoff

R2 の stable `thumb.webp` object は更新済みだが、production manifest の
`thumbUrl?v=<sha256>` はこの PR の merge 後に deploy workflow が canonical R2 prefix を同期して
再生成する。Fable 側の per-cell viewer integration と同じ deploy で manifest を更新し、古い
browser cache key を廃棄する。

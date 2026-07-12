# web — 比較ビューアフロントエンド

Vite 8 + React 19 + Three.js (WebGLRenderer)。設計根拠は `docs/research/viewer-hosting-merged.md`。

## 実行

```powershell
cd web

uv run --project ../bench bench-harness site-data-snapshot `
  ../outputs/site-data `
  ../tasks/tasks.json `
  src/data/model-registry.json `
  public/manifest.json `
  --expected-failure partcrafter/chrome-espresso-machine `
  --allow-partial

pnpm install
pnpm dev
```

`--allow-partial` はフロントエンド開発専用。存在する全セルを本番と同じ契約で検証し、
`partial: true` の manifest を生成する。省略時は 11 モデル x 25 課題の全セルを要求する。
`pnpm dev` は partial manifest を警告付きで許可するが、`pnpm build` は拒否する。

## Worker の GLB 配信契約

本番の `/run-assets/<model>/<task>/output.glb` と、生成済みの場合の
`/run-assets/<model>/<task>/thumb.webp` は R2 binding からストリーミングする。
通常 GET と HEAD に加え、単一の `bytes` Range(`start-end` / `start-` / `-suffix`)、
`If-None-Match`、強 ETag の `If-Range` を処理する。複数 Range と未知の range unit は
通常 GET として扱い、壊れた単一 Range は 400、満たせない単一 Range は 416 を返す。
Worker は R2 metadata より優先して GLB を `model/gltf-binary`、thumbnail を `image/webp`
として返す。Hunyuan3D 2.1 の地域制限は両方に同じ順序で適用される。

### Production cache 方針

`/run-assets/*` では Workers Caching を有効化せず、Cloudflare へ届いた request は Worker が
geo 判定してから R2 の条件付き取得 / 単一 Range 取得を実行する。GLB の
`206 Partial Content` は R2 native Range を正本とし、Cloudflare edge に full `200` を
保存して slice させない。

Hunyuan3D 2.1 の allowed response (GLB / thumbnail、200 / 206 / 304) は常に
`Cache-Control: no-store` とし、取得後に別地域へ移動した browser が保存済み response を
再利用して geo 判定を迂回することも禁止する。manifest の restricted URL は cache-policy
version を含み、この契約以前の public / immutable URL も現在の UI から再利用しない。
unrestricted asset だけが immutable / short-lived cache policy を使う。Free plan の
512 MB cacheable object 上限を超える最大 GLB
(595,904,276 bytes / 約 568.3 MiB) も R2 native Range で配信する。

`wrangler.jsonc` に `cache.enabled` を追加したり、zone Cache Rule で `/run-assets/*` を
cacheable にしてはならない。将来変更する場合は geo-restricted path を uncached gateway /
entrypoint に分離し、allowed / blocked region の cache HIT を含む本番検証を先に行う。

2026-07-12 の production 検証記録と Cloudflare 仕様へのリンクは
`docs/runs/2026-07-custom-domain.md` を参照。

Workers runtime とローカル R2 binding を使う契約テストは次で実行する。

```powershell
pnpm test:worker
```

## モデル出力サムネイル

Issue #66 の thumbnail は既存 `ViewerCore` を pinned Chromium で動かして撮影する。
カメラ、unit-box framing、PBR/RoomEnvironment、orientation fix はサイト本体と同じコードを通る。
出力は透明背景の 320 x 320 WebP で、各成功 cell の `thumb.webp` として R2 に置く。

初回だけ Playwright の pinned Chromium を導入する。

```powershell
pnpm thumbnail:install-browser
```

1 個のローカル GLB を確認する例:

```powershell
pnpm thumbnail:render -- `
  --input ../outputs/site-data/triposr/cartoon-apple/output.glb `
  --output ../outputs/.thumbs/triposr-cartoon-apple.webp `
  --model triposr `
  --backend swiftshader
```

R2 の全 matrix を検証し、274 success cell を 1 個ずつ生成・publish する例:

```powershell
pnpm thumbnail:generate -- s3://3dgen-runs/site-data `
  --expected-failure partcrafter/chrome-espresso-machine `
  --backend gpu `
  --report ../outputs/thumbnail-generation-report.json
```

`R2_ENDPOINT`、`R2_ACCESS_KEY_ID`、`R2_SECRET_ACCESS_KEY` が必須。`gpu` はオーナーの
Windows/ANGLE D3D11 canonical lane 用で、hardware D3D11 以外へ解決した場合は失敗する
(ローカル probe は RTX 4070 Ti を確認済み)。CI や GPU の無い環境は `swiftshader` を指定する。
backend の自動 fallback はない。

通常実行は、R2 の source ETag/size と renderer fingerprint が一致し、既存 WebP の
HEAD/GET/decode/hash 検証も通った cell を GLB download なしで skip する。`--force` は全選択 cell
を再生成する。publish 後の完全性だけを確認する場合は次を使う。

```powershell
pnpm thumbnail:check -- s3://3dgen-runs/site-data `
  --expected-failure partcrafter/chrome-espresso-machine `
  --backend gpu `
  --report ../outputs/thumbnail-check-report.json
```

`--model <id>` / `--task <id>` で明示的に絞り込める。S3 SDK の retry は無効で、source の
conditional GET、WebGL、encode、PUT、publish 後検証のどこかが失敗すればその cell で停止し、
非 0 で終了する。暗黙 retry、別 renderer、リファレンス画像への代替は行わない。

pure inventory/cache tests と実 Chromium/SwiftShader smoke は `pnpm test:thumbnails` で実行する。
設計・バージョン根拠は `docs/research/thumbnail-generation-codex.md` を参照。

## 構成

- `src/viewer/ViewerCore.ts` — **React 非依存**のビューアコア。単一 canvas + scissor viewport で全ペインを 1 つの WebGL コンテキストに描画。カメラ同期、表示モード(PBR / wireframe / matcap / normal / UV checker)、バウンディングボックス正規化、画面外ペインのスキップ
- `src/viewer/ViewerContext.tsx` / `ViewerPane.tsx` — React 側の薄いラッパー
- `src/viewer/loadModel.ts` — GLB ローダー(meshopt 配線済み。KTX2 / Draco はアセットパイプライン導入時に追加)
- `thumbnail-render.html` / `src/thumbnail-render.ts` — production UI から独立した Playwright 用 render page
- `scripts/generate-thumbnails.mjs` — R2 inventory、増分生成、publish、freshness audit

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

本番の `/run-assets/<model>/<task>/output.glb` は R2 binding からストリーミングする。
通常 GET と HEAD に加え、単一の `bytes` Range(`start-end` / `start-` / `-suffix`)、
`If-None-Match`、強 ETag の `If-Range` を処理する。複数 Range と未知の range unit は
通常 GET として扱い、壊れた単一 Range は 400、満たせない単一 Range は 416 を返す。

Workers runtime とローカル R2 binding を使う契約テストは次で実行する。

```powershell
pnpm test:worker
```

## 構成

- `src/viewer/ViewerCore.ts` — **React 非依存**のビューアコア。単一 canvas + scissor viewport で全ペインを 1 つの WebGL コンテキストに描画。カメラ同期、表示モード(PBR / wireframe / matcap / normal / UV checker)、バウンディングボックス正規化、画面外ペインのスキップ
- `src/viewer/ViewerContext.tsx` / `ViewerPane.tsx` — React 側の薄いラッパー
- `src/viewer/loadModel.ts` — GLB ローダー(meshopt 配線済み。KTX2 / Draco はアセットパイプライン導入時に追加)

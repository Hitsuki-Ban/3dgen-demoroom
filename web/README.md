# web — 比較ビューアフロントエンド

Vite 8 + React 19 + Three.js (WebGLRenderer)。設計根拠は `docs/research/viewer-hosting-merged.md`。

## 実行

```powershell
cd web
pnpm install
pnpm dev
```

## 構成

- `src/viewer/ViewerCore.ts` — **React 非依存**のビューアコア。単一 canvas + scissor viewport で全ペインを 1 つの WebGL コンテキストに描画。カメラ同期、表示モード(PBR / wireframe / matcap / normal / UV checker)、バウンディングボックス正規化、画面外ペインのスキップ
- `src/viewer/ViewerContext.tsx` / `ViewerPane.tsx` — React 側の薄いラッパー
- `src/viewer/loadModel.ts` — GLB ローダー(meshopt 配線済み。KTX2 / Draco はアセットパイプライン導入時に追加)
- `src/demo/dummyModels.ts` — ベンチ成果物が届くまでの開発用ダミー(細分化と材質の違うトーラスノット)

## 未実装(今後の PR)

- ベンチ manifest(JSON)からの課題/モデル一覧ロード(bench 側 meta.json スキーマ確定後)
- テクスチャ solo view、統計テーブル、ライセンスバッジの実データ化
- KTX2/Draco デコーダ配置、R2 からのアセットフェッチ、geo 制限ペインのプレースホルダ
- Cloudflare Workers デプロイ(`wrangler.jsonc`)、i18n 構造

# ビューア / ホスティング 突き合わせ結論(merged)

- 確定日: 2026-07-08
- 元資料: `viewer-hosting-fable.md` / `viewer-hosting-codex.md`(独立調査、2026-07-07)
- 本ドキュメントが設計判断の根拠。以後の変更は PR で行う

## 両調査の一致点(そのまま採用)

- **単一 canvas + 単一 `WebGLRenderer` + マルチビューポート**(WebGL コンテキスト上限 8〜16 の回避、geometry/texture/loader cache の共有)。ペインごとの複数 canvas は禁止
- **WebGLRenderer 採用、WebGPURenderer は見送り**(KTX2 まわりの未成熟、比較ビューアに WebGPU の利点なし)。WebGPU は将来ブランチで検証
- **カメラ同期**: マスター OrbitControls の状態を毎フレーム全ペインに適用。デフォルト lock、必要時のみ per-pane unlock
- **統計はオフライン事前計算**(`gltf-transform inspect` → JSON manifest)。ブラウザで測らない
- **アセットパイプライン**: raw 保存 → inspect/validate → dedup/prune/weld → **meshopt 既定**(Draco はオプション)→ **KTX2**(color/emissive = ETC1S、normal/ORM = UASTC + Zstd)→ R2
- **Cloudflare: Workers Static Assets(アプリ)+ R2 カスタムドメイン(GLB/KTX2/splat)**。Pages 不採用。`r2.dev` 本番禁止。25MiB/ファイル制限のためバイナリは初日から R2 に分離
- **3DGS は optional provider**: Spark (`@sparkjsdev/spark`) を dynamic import。配信は SOG/SPZ、raw PLY は保存のみ。第二エンジン(Babylon/gsplat.js)は混ぜない。非対応形式は fail fast

## 相違点の裁定

**素の Three.js(Codex 推奨) vs React + R3F(Fable 推奨)** → 決定: **React 19 シェル + ビューアコア分離**

- UI シェル(ギャラリー、統計テーブル、フィルタ、shadcn/ui)は React 19 + Vite 8
- ビューアコアは **React に依存しない TypeScript クラス**(renderer / scene 管理 / scissor 計算 / camera sync store / material override)として実装し、React からは薄いラッパー component で mount する
- scissor/viewport の第一候補は drei `<View>` だが、コアを分離しておくことで、抽象が邪魔になったら React を剥がさずに自前 scissor 実装へ差し替えられる — Codex の懸念(低レベル制御)と Fable の要件(shadcn/ui との統合)を両立する
- フロント実装は Fable 担当(役割分担どおり)

## 実装仕様に昇格する Codex 調査の知見

- ペインは transparent placeholder、毎フレーム `getBoundingClientRect()` から scissor 計算
- **バウンディングボックス正規化必須**(中心原点・同一最大径。framing 差で比較が濁るのを防ぐ)
- ワイヤーフレームは表示中のみ生成し、切替時に dispose(高ポリ対策)
- テクスチャ solo view は元 material から map を取り出し unlit に貼る
- 表示モード: PBR / wireframe overlay / matcap / normal / UV checker / texture solo(baseColor・normal・ORM・emissive)
- MIME: `.glb`=`model/gltf-binary`、`.ktx2`=`image/ktx2`。**`.glb`/`.ktx2` は R2 カスタムドメインの default cached extensions に含まれない可能性があるため Cache Rule を明示設定**
- Cache-Control: ハッシュ付きアセット `max-age=31536000, immutable` / manifest `max-age=0, must-revalidate`
- KTX2 は `ktx validate --gltf-basisu`、color=sRGB / normal・ORM=linear、寸法 4 の倍数
- 初期は postprocessing を入れない(scissor と相性問題)
- デプロイ: `wrangler deploy` + GitHub Actions(`CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN` を secrets に)

## 確定バージョン(2026-07-07 npm 確認値)

`three@0.185.x` / `vite@8.1.x` / `react@19.2.x` / `@react-three/fiber@9.6.x` / `@react-three/drei@10.7.x` / `@gltf-transform/cli@4.4.x` / `gltfpack@1.2.x` / `@sparkjsdev/spark@2.1.x` / `@playcanvas/splat-transform@2.7.x` / `wrangler@4.107.x` / `@cloudflare/vite-plugin@1.43.x`

## 無料枠の見込み

R2: 10GB-月 / Class B 10M reads-月 / egress 無料 → 50 課題 × 10 モデル × 20MB ≈ 10GB でほぼ無料枠内。超過時も storage $0.015/GB-月程度。Workers Static Assets は無料・無制限(静的アセット配信)。

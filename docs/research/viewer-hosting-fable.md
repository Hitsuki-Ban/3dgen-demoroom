# Three.js 比較ビューア構成と Cloudflare ホスティング調査(Fable 側)

- 調査日: 2026-07-07
- 調査方法: Claude (Sonnet) リサーチエージェントによる Web 検索・npm レジストリ直接確認
- 対をなす Codex 側調査: `viewer-hosting-codex.md`(突き合わせ結果は `viewer-hosting-merged.md` 予定)

---

## 1. Recommended Frontend Architecture

**Framework & tooling**

- **Vite 8** (npm latest `8.1.3`, released Mar 2026) — now ships Rolldown (Rust bundler) by default. Per project convention, scaffold/manage with **Vite+** (VoidZero's unified CLI wrapping Vite 8 + Vitest 4.1 + Oxlint/Oxfmt) — alpha-stage but MIT-licensed and framework-agnostic; low-risk for tooling.
- **React + react-three-fiber (R3F)**, not vanilla three.js. R3F (`@react-three/fiber@9.6.1`) and drei (`@react-three/drei@10.7.7`) actively maintained by Poimandres in 2026. shadcn/ui (React+Tailwind) is the UI baseline anyway → R3F avoids a second UI paradigm and gives drei's helpers (`useGLTF` suspense+caching, `Bounds`/`Center` auto-framing, `Environment`, `Stats`, `PerformanceMonitor`).
- **Renderer: `WebGLRenderer`, not `WebGPURenderer`.** three.js is at **r185** (`three@0.185.1`, 2026-07-01). WebGPURenderer has been "production ready" with WebGL2 fallback since r171, and WebGPU ships by default in Chrome/Edge/Firefox/Safari 26 — but its benefits (compute shaders, massive instancing) are irrelevant to a static-GLB gallery, and its KTX2/compressed-texture path still has open bugs as of mid-2026 (`mrdoob/three.js#31690`).

**Viewer architecture — the core design decision**

- **Do not spin up one `<canvas>`/WebGL context per model.** Browsers hard-cap WebGL contexts per tab: Chrome ~16, Firefox similar, mobile as low as 8 — exceeding it silently kills the oldest context (`webglcontextlost`). 6–10 models per task × several tasks mounted = blown past fast.
- **Use a single shared canvas/WebGL context with drei's `<View>` component** (or hand-rolled `renderer.setScissor()`/`setViewport()`). `<View>` renders N independent virtual viewports — each tracking a DOM element's rect — through one shared canvas and one render loop. Community-recommended pattern (pmndrs/react-three-fiber discussions #2716, #572; three.js forum "Canvases vs. Views?").
- **`<model-viewer>`** (`@google/model-viewer@4.3.1`) is the simplest embed but each instance owns its own context, and it's a closed abstraction — no clean wireframe/matcap/UV-checker swapping or texture-channel inspection. Not suited to this dev-facing inspection tool.
- **Camera-sync**: one "master" `OrbitControls`, copy camera transform (position/quaternion/target) into every viewport's camera each frame — all N models rotate/zoom in lockstep.
- **Real-world precedent**: **3D Arena** (HF Space, arXiv 2506.18787) renders side-by-side with Gradio Model3D — Babylon.js for meshes + gsplat.js for splats — and already implements **wireframe toggle + polygon count per asset**, validating this feature set for this audience.
- **Lazy loading**: mount viewers via `IntersectionObserver` when entering viewport; dispose when far away.

**Mesh inspection features — free vs. build**

- Free from three.js core: wireframe (`material.wireframe`), normal view (`MeshNormalMaterial`), matcap (`MeshMatcapMaterial`), live `renderer.info.render.triangles`/`.calls`.
- To build: UV-checker mode (swap `.map` to checker texture), texture-channel inspector panel (`material.map`/`.normalMap`/`.roughnessMap`/`.metalnessMap` + `image.width/height` + thumbnail canvas).
- **File size / vertex / triangle / texture stats precomputed offline**, not measured in-browser: `gltf-transform inspect <file>.glb` (`@gltf-transform/cli`, core `@gltf-transform/core@4.4.1`) at build time → JSON manifest → frontend renders stats table. No runtime cost.
- **Don't depend on `donmccurdy/three-gltf-viewer` as a library** — standalone app, not an npm package. Use its source as reference for environment lighting/tone-mapping/inspector wiring.

## 2. Recommended Asset Pipeline (offline, precomputed)

Per GLB, in a Node.js build script:

1. **Clean up**: `gltf-transform dedup` → `prune` → `weld`.
2. **Geometry compression**: prefer **meshopt** over Draco as default — comparable ratios, materially faster decode, compresses further under gzip/brotli at CDN edge. Keep Draco (`draco3d@1.5.7`) as per-asset override where absolute size matters more than decode latency.
3. **Texture compression**: **KTX2/Basis Universal** — UASTC for hero textures/normal maps, ETC1S for secondary/albedo. Biggest GPU-memory win (stays compressed in VRAM).
4. **Single-command option**: **gltfpack** (`gltfpack@1.2.0`, `-cc` meshopt + `-tc` KTX2) for batch; **glTF-Transform** is the composable JS-API for a repeatable pipeline that also emits the stats manifest in the same script. Reasonable: gltf-transform pipeline + stats, invoking meshopt/texture-compress.
5. **Emit stats manifest**: vertex/triangle/material/texture counts + byte sizes → JSON consumed by frontend.
6. **Target**: optimized GLBs in 5–50MB range.

**Gaussian splats**(一部モデルの副次出力):

- Render with **Spark** (`@sparkjsdev/spark@2.1.0`, MIT, World Labs, May 2026) — most actively developed, first-class three.js citizen: `SplatMesh` drops into a `THREE.Scene` alongside meshes, sharing renderer/camera/controls — critical for camera-sync comparison. Widest format range (PLY incl. compressed, SPZ, SPLAT, KSPLAT, SOG).
- Alternatives: `@mkkellogg/gaussian-splats-3d@0.4.7` (three.js `DropInViewer`), HF `gsplat@1.2.9` (independent renderer, what 3D Arena uses). Staying single-engine with Spark beats the two-engine approach.
- **Offline conversion**: PlayCanvas **`splat-transform`** CLI → **SOG** (~15–20x smaller than raw PLY, Morton-ordered, GPU-ready) or **SPZ** (Niantic, v4.0 ~May 2026, emerging interchange default). Never serve raw PLY to browsers.

## 3. Recommended Cloudflare Setup

**Products**: **Workers Static Assets**(アプリ本体)+ **R2**(大容量アセット)。Pages は使わない。

- Cloudflare は投資を Workers に集約中; Pages はメンテナンスモード(バグ修正のみ)。2026 年新規プロジェクトは Workers Static Assets 直行が推奨。

**Setup outline**:

1. Vite/React app + 公式 `@cloudflare/vite-plugin` (`1.43.0`) — `vite build` 出力が直接 Worker に配線される。
2. `wrangler.jsonc`: `assets` block (`directory: "./dist"`, `binding: "ASSETS"`)。`wrangler deploy` (`wrangler@4.107.0`)。
3. **Critical constraint**: Workers Static Assets は **1 ファイル 25 MiB 上限**(ハードリミット)、ファイル数 20,000 (Free) / 100,000 (Paid)。5–50MB の GLB / splat は**Worker 側に置かない**。
4. **GLB/KTX2/splat はすべて R2 バケットへ**:
   - 公開アクセスは**カスタムドメイン**(例 `assets.yoursite.com`)経由。**`r2.dev` サブドメインは本番禁止**(明示的にレート制限あり、数百 req/s で 429)。
   - CORS: dashboard または `wrangler r2 bucket cors set <bucket> --file cors.json`
     ```json
     [{
       "AllowedOrigins": ["https://yoursite.com"],
       "AllowedMethods": ["GET", "HEAD"],
       "AllowedHeaders": ["*"],
       "MaxAgeSeconds": 3600
     }]
     ```
   - コンテンツハッシュ付き最適化 GLB には `Cache-Control: public, max-age=31536000, immutable`。
5. フロントは `https://assets.yoursite.com/<task>/<model>.glb` を R2 カスタムドメインから直接 fetch。Worker はアプリシェルのみ配信。

**Free-tier fit**: R2 無料枠 = ストレージ 10 GB-月、Class A (write) 1M ops/月、Class B (read) 10M ops/月、**egress 恒久無料**。50 課題 × 8 モデル × 平均 ~20MB ≈ 8GB → **無料枠に収まる**。スケール時の現実的な制約は Class B read ops(超過 $0.36/million)。

## 4. Risks / Gotchas

- **WebGL コンテキスト上限(タブあたり 8–16)**が最大の設計トラップ — 最初から単一 canvas + scissor viewport / drei `<View>` 設計にコミットする。
- **Workers Static Assets の 25 MiB/ファイル上限** — バイナリアセットとアプリシェルのディレクトリ/パイプラインを初日から分離。
- **`r2.dev` は本番ドメインではない** — ローンチ前に必ずカスタムドメイン設定。
- **WebGPURenderer + KTX2 は未成熟**(2026 年中頃時点で open issues)— WebGLRenderer が正解。
- **Draco vs meshopt**: 実際のモデルセットで両方テストする。ワークロード依存。
- **Splats の 2 エンジン罠**: Babylon + gsplat.js 構成はカメラ状態共有が困難。Spark で three.js 単一エンジンに保つ(ライブラリが若い ~1 年のリスクは許容)。
- **圧縮 splat フォーマットのみ配信**(SOG / SPZ)、raw PLY は配信しない。
- **Vite+ / Void は両方 alpha** — ローカルツーリングに Vite+ は可、デプロイは当面 `wrangler deploy`(battle-tested)を使う。
- **Cache Reserve は 1 リソース 512MB 上限** — 5–50MB では無関係だが、未変換の raw データをバケットに混ぜない。

## 5. Source URLs Consulted

- https://github.com/mrdoob/three.js/releases
- https://threejs.org/docs/pages/WebGPURenderer.html
- https://discourse.threejs.org/t/webgpurenderer-compressed-texture-ktx2-basis/69362
- https://github.com/mrdoob/three.js/issues/31690
- https://threejs.org/docs/pages/KTX2Loader.html
- https://www.utsubo.com/blog/threejs-2026-what-changed
- https://github.com/pmndrs/react-three-fiber/discussions/2716 / /discussions/572
- https://drei.docs.pmnd.rs/
- https://discourse.threejs.org/t/canvases-vs-views/55858
- https://webglfundamentals.org/webgl/lessons/webgl-multiple-views.html
- https://github.com/greggman/virtual-webgl
- https://issues.chromium.org/issues/40543269 / https://bugzilla.mozilla.org/show_bug.cgi?id=1421481
- https://modelviewer.dev/docs/faq.html
- https://huggingface.co/spaces/dylanebert/3d-arena / https://arxiv.org/html/2506.18787v1
- https://developers.cloudflare.com/workers/static-assets/ (+ migration-guides, billing-and-limitations)
- https://developers.cloudflare.com/changelog/post/2025-09-02-increased-static-asset-limits/
- https://mecanik.dev/en/posts/cloudflare-pages-vs-workers-which-to-use-in-2026/
- https://developers.cloudflare.com/r2/pricing/ / /r2/platform/limits/ / /r2/buckets/public-buckets/ / /r2/buckets/cors/
- https://developers.cloudflare.com/rules/origin-rules/tutorials/point-to-r2-bucket-with-custom-domain/
- https://developers.cloudflare.com/cache/advanced-configuration/cache-reserve/
- https://nubbo.app/blog/cloudflare-r2-free-tier/
- https://github.com/sparkjsdev/spark / https://sparkjs.dev/
- https://github.com/mkkellogg/GaussianSplats3D / https://github.com/huggingface/gsplat.js/
- https://github.com/playcanvas/supersplat / https://github.com/playcanvas/splat-transform
- https://blog.playcanvas.com/playcanvas-open-sources-sog-format-for-gaussian-splatting/
- https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/
- https://radiancefields.substack.com/p/gaussian-splatting-in-may-2026
- https://gltf-transform.dev/ / https://gltf-transform.dev/cli
- https://meshoptimizer.org/gltf/ / https://www.npmjs.com/package/gltfpack
- https://github.com/donmccurdy/three-gltf-viewer
- https://vite.dev/blog/announcing-vite8 / https://www.builder.io/blog/vite-8-vite-plus-void
- npm registry direct queries: three, @react-three/fiber, @react-three/drei, @gltf-transform/core, gltfpack, @mkkellogg/gaussian-splats-3d, gsplat, @sparkjsdev/spark, meshoptimizer, draco3d, @google/model-viewer, vite, @cloudflare/vite-plugin, wrangler

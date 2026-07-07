# Three.js 比較ビューア構成と Cloudflare ホスティング調査

- 確認日: 2026-07-07 JST
- 対象: 3D 生成ベンチ結果の GLB メッシュ、テクスチャ、場合により 3DGS を、ブラウザで横並びに検分できる公開展示サイト
- 前提: Vite + pnpm、Three.js、静的サイト、Cloudflare hosting、large assets は R2
- 調査方針: Fable 側の同テーマ文書は読まず、公式 docs / npm registry / GitHub release / 公開実装を確認した。

## 結論

推奨フロントエンド構成は **Vite + TypeScript + vanilla Three.js**。ビューアは **単一 `WebGLRenderer` + 単一 canvas + `setViewport` / `setScissor` による複数 viewport** を主構成にする。6-10 モデルの横並び比較では、複数 canvas / 複数 renderer は WebGL context 数上限と GPU memory 重複が明確な負債になる。

React を採用する場合の代替は **React 19 + `@react-three/fiber` + `@react-three/drei` の `View`**。これは単一 canvas 複数 viewport の React 向け抽象なので、設計思想は同じ。ただしこのプロジェクトは展示型の比較ビューアであり、カメラ同期、material override、GLB/3DGS loader、統計 overlay を細かく制御するため、最初は素の Three.js の方が状態管理と性能調整が読みやすい。

Cloudflare は **Workers Static Assets + R2 custom domain** を推奨する。アプリ本体と小さい hashed JS/CSS/image は Workers Static Assets、25 MiB を超えうる GLB/KTX2/3DGS は R2 bucket + custom domain (`assets.example.com`) に置く。Pages はまだ利用可能だが、新規 Vite 静的サイトでは Workers Static Assets の方が Cloudflare の現在の投資方向に合う。

3DGS は初期必須機能にせず、**Spark (`@sparkjsdev/spark`) を動的 import する optional provider** とする。離線変換・清理は PlayCanvas SuperSplat / `@playcanvas/splat-transform` を使う。

## バージョン確認

| ライブラリ / ツール | 確認バージョン | 公開日 / 更新日 | 判断 |
|---|---:|---:|---|
| `three` | 0.185.1 | 2026-07-01 | 主 renderer。Three.js site では r185。 |
| `vite` | 8.1.3 | 2026-07-02 | Vite + pnpm の静的 build。 |
| `react` | 19.2.7 | 2026-06-01 | R3F 採用時の前提。 |
| `@react-three/fiber` | 9.6.1 | 2026-04-28 | React 19 対応世代。 |
| `@react-three/drei` | 10.7.7 | 2025-11-13 | `View` で single canvas multi-view。 |
| `@google/model-viewer` | 4.3.1 | 2026-06-04 | 簡易 GLB preview 用。主比較器にはしない。 |
| `@gltf-transform/cli` / `core` | 4.4.1 | 2026-07-02 | inspect / optimize / KTX2 pipeline。 |
| `meshoptimizer` / `gltfpack` | 1.2.0 | 2026-06-30 | meshopt compression と高速 web 配信。 |
| `@mkkellogg/gaussian-splats-3d` | 0.4.7 | 2025-01-25 | 旧 3DGS 実装。新規主線にはしない。 |
| `@sparkjsdev/spark` | 2.1.0 | 2026-05-18 | 3DGS optional provider の本命。 |
| `gsplat` | 1.2.9 | 2025-07-12 | 3D Arena で利用例あり。Three.js scene 統合は弱い。 |
| `@playcanvas/splat-transform` | 2.7.1 | 2026-06-30 | 3DGS 変換・圧縮 CLI。 |
| `@playcanvas/supersplat-viewer` | 1.27.0 | 2026-07-01 | standalone viewer には強いが別 engine。 |
| `playcanvas` | 2.20.6 | 2026-07-06 | SuperSplat viewer の runtime 系。 |
| `wrangler` | 4.107.0 | 2026-07-02 | Workers deploy / R2 CORS 操作。 |
| `@cloudflare/vite-plugin` | 1.43.0 | 2026-07-02 | Workers + Vite integration。 |

## 横並びビューア方式

| 方式 | 利点 | 問題 | 採用判断 |
|---|---|---|---|
| 複数 canvas / 複数 `WebGLRenderer` | 実装が一番簡単。2 pane の spike は速い。 | WebGL context 数上限が 8-16 程度に当たる。geometry / texture / shader が renderer ごとに重複し、GPU memory を浪費する。 | spike 以外では避ける。 |
| 単一 canvas + `setViewport` / `setScissor` | 1 context で複数 pane を描ける。loader cache、texture、environment を共有できる。 | DOM rect と pointer hit test、scroll/resize、postprocessing の取り回しは自前実装。 | **主採用**。 |
| R3F + drei `View` | React DOM と single canvas multi-view を統合しやすい。 | R3F/R3F ecosystem 依存。低レベル scissor / dispose / postprocess 調整が抽象化される。 | React 採用時の代替。 |
| `<model-viewer>` | GLB 1 点の簡易 preview、poster、AR、share page が楽。 | カメラ同期、debug material、3DGS、texture map solo、統計 overlay の自由度が足りない。 | 主比較器には不採用。簡易 preview 用に限定。 |

実装の基本形:

- canvas は viewport 全体に 1 枚だけ置き、HTML 側の各 pane は transparent placeholder として配置する。
- 毎 frame、pane の `getBoundingClientRect()` から scissor / viewport を計算する。
- pane ごとに `scene` / `camera` / `modelRoot` は分けるが、renderer、loader cache、decoder、environment texture、camera sync store は共有する。
- active pane の orbit 操作だけが共有 camera state を更新し、他 pane は次 frame で同じ target / radius / azimuth / polar / zoom を適用する。
- 速度比較と画質比較を混同しないため、デフォルトは camera lock on、必要時だけ per-pane unlock を許可する。

## メッシュ検分機能

ゲームグラフィックス開発者向けには、見た目だけでなく topology / texture / file budget を同時に見せる必要がある。

必須:

- PBR 表示: 元の material / texture / environment をそのまま表示。
- Wireframe overlay: `WireframeGeometry` または material override。高 poly では overlay を間引く。
- Matcap 表示: texture や lighting を外し、形状と面の連続性を検分。
- Normal 表示: 法線方向、スムージング破綻、裏面を確認。
- UV checker 表示: unwrap の歪み、seam、texel density を確認。
- Texture map solo: baseColor、normal、metallic/roughness/occlusion channel、alpha、emissive を個別表示。
- Stats: triangle count、vertex count、mesh count、material count、texture count、texture dimensions、GLB size、optimized size、extensions。
- Download links: raw GLB、optimized GLB、stats JSON、thumbnail。

実装メモ:

- global debug mode は `Scene.overrideMaterial` または material swapping で実装する。
- texture solo view は元 material の `map` / `normalMap` / `emissiveMap` / ORM texture を取り出し、unlit material に貼る。
- triangle / vertex count は runtime で `BufferGeometry.index` / `attributes.position` から計算できるが、一覧 UI は offline stats JSON を優先する。
- Bounding box normalize は必須。各モデルを中心原点・同一最大径に合わせ、比較が framing に左右されないようにする。
- 3D Arena の論文も、将来は topology assessment に wireframe view と polygon count を分離表示する方向を提案している。

## GLB 最適化パイプライン

推奨は **raw source を保存し、公開用 artifact を別に作る** 方式。

1. Raw output を保存する。
2. `gltf-transform inspect` と validator で統計・エラーを JSON/Markdown に出す。
3. texture / material / geometry を必要最小限だけ整理する。
4. Meshopt/gltfpack で geometry と buffer を web 向けに最適化する。
5. Texture-heavy asset は KTX2/BasisU に変換する。
6. 25 MiB を超える可能性がある公開 asset は R2 に置く。
7. 公開 manifest に raw / optimized / thumbnail / stats / license / model / prompt を紐づける。

基本コマンド:

```powershell
# Inspect / validate
pnpm dlx @gltf-transform/cli inspect input.glb --format md
pnpm dlx @gltf-transform/cli inspect input.glb --format csv
pnpm dlx @gltf-transform/cli validate input.glb

# Conservative meshopt optimization
pnpm dlx @gltf-transform/cli optimize input.glb output.meshopt.glb --compress meshopt

# KTX2 texture compression by slot
pnpm dlx @gltf-transform/cli etc1s output.meshopt.glb output.color-ktx2.glb --slots "baseColorTexture,emissiveTexture"
pnpm dlx @gltf-transform/cli uastc output.color-ktx2.glb output.final.glb --slots "normalTexture,occlusionTexture,metallicRoughnessTexture" --zstd 18
```

`gltfpack` も有力。特に native binary は大きい asset と texture compression で速い。

```powershell
gltfpack -i input.glb -o output.meshopt.glb -cc
gltfpack -i input.glb -o output.meshopt.ktx2.glb -cc -tc
gltfpack -i input.glb -o output.meshopt.ktx2-uastc.glb -cc -tc -tu -tq 8
```

判断:

- 既定は Meshopt。Draco は対応範囲が広いが decode cost が高く、geometry 中心なので、この viewer のデフォルトにはしない。
- Three.js loader 側は Meshopt / Draco / KTX2 のすべてを読めるようにしておく。外部モデルや Fable 実装の検証に必要。
- KTX2 は texture-heavy asset で重要。PNG/JPEG/WebP は転送量を減らしても GPU memory では展開される。
- color / emissive は ETC1S/BasisLZ、normal / ORM / quality-sensitive texture は UASTC + Zstd を優先する。
- KTX2 は `ktx validate --gltf-basisu` で検証し、color map は sRGB、normal/ORM は linear、mipmap あり、寸法は 4 の倍数を基本にする。

Three.js loader 設定:

```ts
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/examples/jsm/loaders/DRACOLoader.js';
import { KTX2Loader } from 'three/examples/jsm/loaders/KTX2Loader.js';
import { MeshoptDecoder } from 'three/examples/jsm/libs/meshopt_decoder.module.js';

const ktx2Loader = new KTX2Loader()
  .setTranscoderPath('/basis/')
  .detectSupport(renderer);

const dracoLoader = new DRACOLoader()
  .setDecoderPath('/draco/');

const gltfLoader = new GLTFLoader()
  .setKTX2Loader(ktx2Loader)
  .setDRACOLoader(dracoLoader)
  .setMeshoptDecoder(MeshoptDecoder);
```

## 3DGS レンダリング

3DGS は optional provider として扱う。メッシュ比較サイトの主対象は GLB だが、モデルによって 3DGS が出る場合がある。

| ライブラリ / ツール | 状態 | 形式 | 判断 |
|---|---|---|---|
| Spark (`@sparkjsdev/spark`) | 2.1.0、2026-05-18。World Labs 製、Three.js 統合を明示。 | `.ply` / compressed PLY、`.spz`、`.splat`、`.ksplat`、`.sog` | **採用候補**。`SplatMesh` を Three.js scene に置ける。 |
| `@mkkellogg/gaussian-splats-3d` | 0.4.7、2025-01-25。README で Spark を推奨する方向。 | `.ply`、`.splat`、`.ksplat`、SPZ / compressed PLY support | 参考実装。新規主線にはしない。 |
| `gsplat` / Hugging Face gsplat.js | 1.2.9、2025-07-12。3D Arena で利用例あり。 | 主に `.splat` / `.ply` | 独立 API 色が強く Three.js scene 統合には弱い。 |
| PlayCanvas SuperSplat | editor 2.28.1、2026-06-30。 | `.ply`、compressed PLY、`.sog`、`meta.json`、`.splat`、`.spz`、`.lcc` | viewer ではなく離線編集・変換に使う。 |
| `@playcanvas/splat-transform` | 2.7.1、2026-06-30。 | SOG / SPZ / PLY 変換 | CI/offline pipeline 用。 |

推奨:

- 3DGS asset がある場合だけ `import('@sparkjsdev/spark')` する。
- 公開用 3DGS は `.sog` または `.spz` を優先し、源データとして `.ply` を保存する。
- `.splat` は軽いが spherical harmonics を保持しないケースがあり、品質評価の主形式にしない。
- Spark が対応しない形式は fail fast で unsupported と表示し、別 renderer へ silent fallback しない。
- PlayCanvas SuperSplat viewer は standalone export には便利だが、Three.js 比較ビューア内に第二 engine として混ぜない。

## WebGPU / WebGL 判断

2026-07 時点で Three.js `WebGPURenderer` は公式 docs にあり、WebGPU backend が使えない場合は WebGL2 backend に fallback できる。ただし R3F docs でも「work in progress and not fully backward-compatible」とされる。今回の比較ビューアでは、GLTFLoader、KTX2、debug material、3DGS、postprocessing、browser coverage の安定性が重要なので、初期実装は **`WebGLRenderer` を採用**する。

WebGPU は次の条件が揃った段階で別 branch で検証する:

- GLB debug modes が WebGL と同一に見える。
- Spark / 3DGS optional provider が問題なく動く。
- postprocessing を使う場合に scissor viewport と矛盾しない。
- Safari / mobile Chrome / Firefox の対象環境で fallback 挙動が確認できる。

## Cloudflare 構成

推奨構成:

```text
app.example.com
  Workers Static Assets
  - index.html
  - JS/CSS chunks
  - small thumbnails / icons
  - manifest JSON if 25 MiB 以下

assets.example.com
  R2 public bucket with custom domain
  - *.glb
  - *.ktx2
  - *.spz / *.sog / *.ply
  - large thumbnails
  - stats JSON / logs
```

理由:

- Workers Static Assets は静的 asset request が無料・無制限で、asset storage 追加費用もない。
- Workers Static Assets / Pages の単一 static asset 上限は 25 MiB。5-50MB GLB を扱う本プロジェクトでは、大きい asset をアプリ deploy に入れない。
- R2 は 10 GB-month、Class A 100 万、Class B 1000 万まで無料。Standard 超過は storage $0.015/GB-month、Class A $4.50/million、Class B $0.36/million、internet egress は無料。
- R2 custom domain は Cloudflare Cache / WAF / Access / Bot Management を使える。本番で `r2.dev` は使わない。
- Free/Pro/Business の Cloudflare CDN cacheable file size は 512 MB なので、50MB 級 asset は cache 可能。

Workers `wrangler.jsonc` 例:

```jsonc
{
  "$schema": "./node_modules/wrangler/config-schema.json",
  "name": "3dgen-demoroom",
  "compatibility_date": "2026-07-07",
  "assets": {
    "directory": "./dist",
    "not_found_handling": "single-page-application"
  }
}
```

R2 CORS 例:

```json
{
  "rules": [
    {
      "allowed": {
        "origins": ["https://app.example.com"],
        "methods": ["GET", "HEAD"]
      },
      "maxAgeSeconds": 3600
    }
  ]
}
```

適用:

```powershell
pnpm wrangler r2 bucket cors set 3dgen-demoroom-assets --file cors.json
pnpm wrangler r2 bucket cors list 3dgen-demoroom-assets
```

Cache / metadata:

- hashed GLB/KTX2/3DGS: `Cache-Control: public, max-age=31536000, immutable`
- manifest / index: `Cache-Control: public, max-age=0, must-revalidate`
- MIME: `.glb` = `model/gltf-binary`、`.gltf` = `model/gltf+json`、`.ktx2` = `image/ktx2`、`.wasm` = `application/wasm`、`.json` = `application/json`
- R2 custom domain では `.glb` / `.ktx2` が default cached extensions に含まれない可能性があるため、asset path に Cache Everything / Cache Rule を設定する。
- CORS 変更後は既存 cache を purge する。

GitHub Actions 方針:

```yaml
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 24
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm run build
      - run: pnpm wrangler deploy
        env:
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
```

## リスクと落とし穴

- 複数 canvas は context 上限と GPU memory 重複で壊れやすい。最初から single renderer を前提にする。
- Scissor viewport は pointer 座標、scroll、DPR、resize、CSS transform に弱い。pane rect 計算の単体テストか visual smoke test が必要。
- Postprocessing は scissor と相性が悪い pass がある。初期は postprocess を入れない。
- 生成モデルの raw GLB は座標系、単位、中心、scale が揃わない。normalize しない比較は信頼しない。
- Wireframe overlay は高 poly で重い。表示中だけ生成し、pane 切替時に dispose する。
- KTX2 / Meshopt / Draco decoders は asset pipeline と loader path の version mismatch に注意する。
- KTX2 は見た目差が出やすい。normal / ORM は UASTC、color は ETC1S など用途別に品質を決める。
- 25 MiB を超える asset を Workers Static Assets / Pages deploy に混ぜない。R2 へ分離する。
- R2 `r2.dev` は本番配信用ではない。custom domain を使う。
- `.glb` / `.ktx2` cache は default cache behavior 任せにしない。
- 3DGS は形式が乱立している。viewer は Spark 対応形式だけを明示し、変換は offline pipeline に閉じる。
- WebGPU は魅力的だが、初期の展示サイトでは WebGLRenderer の安定性を優先する。

## 出典 URL

### Three.js / Viewer UX

- https://threejs.org/
- https://threejs.org/docs/pages/WebGLRenderer.html
- https://threejs.org/docs/pages/WebGPURenderer.html
- https://threejs.org/manual/en/webgpurenderer.html
- https://threejs.org/docs/pages/GLTFLoader.html
- https://threejs.org/docs/pages/KTX2Loader.html
- https://threejs.org/docs/pages/DRACOLoader.html
- https://webglfundamentals.org/webgl/lessons/webgl-multiple-views.html
- https://threejsfundamentals.org/threejs/lessons/threejs-multiple-scenes.html
- https://discourse.threejs.org/t/how-many-renderers-is-too-many/58774
- https://discourse.threejs.org/t/canvases-vs-views/55858
- https://r3f.docs.pmnd.rs/api/canvas
- https://r3f.docs.pmnd.rs/tutorials/v9-migration-guide
- https://drei.docs.pmnd.rs/portals/view
- https://github.com/google/model-viewer/releases
- https://modelviewer.dev/examples/loading/

### 既存比較サイト / 参考 UI

- https://huggingface.co/spaces/3d-arena/3d-arena
- https://huggingface.co/spaces/3d-arena/3d-arena/tree/main
- https://huggingface.co/spaces/3d-arena/3d-arena/blob/main/package.json
- https://huggingface.co/spaces/3d-arena/3d-arena/blob/main/src/routes/Vote.svelte
- https://arxiv.org/html/2506.18787v1
- https://www.meshy.ai/
- https://www.meshy.ai/compare
- https://www.tripo3d.ai/3d-tools/3d-viewer
- https://studio.tripo3d.ai/3d-model-gallery/
- https://hyper3d.ai/

### glTF / GLB / KTX2

- https://gltf-transform.dev/
- https://gltf-transform.dev/cli
- https://gltf-transform.dev/modules/extensions/classes/EXTMeshoptCompression
- https://meshoptimizer.org/gltf/
- https://github.com/zeux/meshoptimizer/releases
- https://github.khronos.org/KTX-Software/ktxtools/index.html
- https://github.com/KhronosGroup/glTF-Validator
- https://raw.githubusercontent.com/KhronosGroup/glTF/main/extensions/2.0/Khronos/KHR_texture_basisu/README.md
- https://raw.githubusercontent.com/KhronosGroup/glTF/main/extensions/2.0/Vendor/EXT_meshopt_compression/README.md
- https://raw.githubusercontent.com/KhronosGroup/glTF/main/extensions/2.0/Khronos/KHR_draco_mesh_compression/README.md

### 3DGS

- https://sparkjs.dev/
- https://sparkjs.dev/docs/overview/
- https://sparkjs.dev/docs/splat-mesh/
- https://github.com/sparkjsdev/spark
- https://github.com/mkkellogg/GaussianSplats3D
- https://github.com/mkkellogg/GaussianSplats3D/releases
- https://github.com/huggingface/gsplat.js/
- https://github.com/playcanvas/supersplat
- https://developer.playcanvas.com/user-manual/supersplat/editor/import-export/
- https://github.com/playcanvas/splat-transform
- https://developer.playcanvas.com/user-manual/gaussian-splatting/formats/sog/
- https://blog.playcanvas.com/playcanvas-open-sources-sog-format-for-gaussian-splatting/
- https://github.com/playcanvas/supersplat-viewer

### Cloudflare

- https://developers.cloudflare.com/workers/static-assets/
- https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/
- https://developers.cloudflare.com/workers/static-assets/binding/
- https://developers.cloudflare.com/workers/static-assets/migration-guides/migrate-from-pages/
- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/workers/vite-plugin/get-started/
- https://developers.cloudflare.com/workers/framework-guides/web-apps/react/
- https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/
- https://github.com/cloudflare/wrangler-action
- https://developers.cloudflare.com/pages/platform/limits/
- https://developers.cloudflare.com/r2/pricing/
- https://developers.cloudflare.com/r2/platform/limits/
- https://developers.cloudflare.com/r2/objects/upload-objects/
- https://developers.cloudflare.com/r2/buckets/public-buckets/
- https://developers.cloudflare.com/r2/buckets/cors/
- https://developers.cloudflare.com/r2/api/s3/api/
- https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/
- https://developers.cloudflare.com/cache/concepts/default-cache-behavior/

# モデル出力サムネイル生成方式の調査

- 確認日: 2026-07-12
- 対象: Issue #66 (`site-data/<model>/<task>/thumb.webp`)

## 結論

サムネイルは Blender で別レンダリングするのではなく、Playwright の pinned Chromium から
既存の Three.js `ViewerCore` を直接動かして撮影し、Sharp で 320 x 320 WebP に変換する。
これにより、カメラ、単位箱正規化、モデル別 orientation fix、RoomEnvironment/PMREM、
ACES tone mapping がサイト本体と同じコード経路になる。Blender の glTF import、Principled
BSDF、color management を介した画像は高品質だが、サイトの WebGL 表示とは別の描画契約に
なるため本用途では採用しない。

274 個の GLB は deploy workflow で毎回描画しない。明示的なオフライン生成コマンドが R2 を
inventory し、1 個ずつ conditional GET で一時ファイルへ流し、常駐する Chromium で順次描画、
検証済み WebP だけを同じ cell に PUT する。source ETag/size/SHA-256 と renderer fingerprint を
R2 custom metadata に保存し、完全一致かつ WebP の再検証が通る場合だけ再利用する。

## バージョンと再現性

生成経路の直接依存は exact pin と lockfile の両方で固定する。

| コンポーネント | 固定版 | 公式確認 |
| --- | --- | --- |
| Playwright | 1.61.1 | [release](https://github.com/microsoft/playwright/releases/tag/v1.61.1)、[Chromium 149.0.7827.55 / revision 1228](https://github.com/microsoft/playwright/blob/v1.61.1/packages/playwright-core/browsers.json) |
| Three.js | 0.185.1 (r185 系) | [r185 release](https://github.com/mrdoob/three.js/releases/tag/r185) |
| Sharp | 0.35.3 | [release](https://github.com/lovell/sharp/releases/tag/v0.35.3) |

canonical recipe は 320 x 320、device scale factor 1、透明背景、PBR、固定 camera/FOV、
WebP quality 85 / alphaQuality 100 / effort 6 とする。異なる OS/GPU 間でピクセルまたは WebP
byte hash の一致は保証しない。正式生成時の browser version、WebGL renderer、入力/出力 hash、
recipe fingerprint を report と object metadata に残す。

無 GPU の検証は Chromium の現行要件に合わせて `--use-gl=angle` と
`--use-angle=swiftshader` を明示する。暗黙の software fallback や別ブラウザ retry は行わず、
初期化不能なら失敗させる。根拠は [Chromium SwiftShader 文書](https://chromium.googlesource.com/chromium/src.git/+/refs/heads/main/docs/gpu/swiftshader.md)
と [Chrome 138 の WebGL software fallback 変更](https://developer.chrome.com/blog/chrome-138-beta)。

## API・フォーマット上の根拠

- Playwright は page/element screenshot と透明背景を提供する: [Screenshots](https://playwright.dev/docs/screenshots)、[page.screenshot](https://playwright.dev/docs/api/class-page#page-screenshot)。
- Three.js の glTF 読み込みと viewer 描画契約: [GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html)、[WebGLRenderer](https://threejs.org/docs/pages/WebGLRenderer.html)、[PMREMGenerator](https://threejs.org/docs/pages/PMREMGenerator.html)。
- Sharp は WebP の quality/alphaQuality/effort を明示でき、出力 metadata を返す: [Output options](https://sharp.pixelplumbing.com/api-output/)。
- R2 は S3 SDK の `ListObjectsV2` / `HeadObject` / `GetObject` / `PutObject` と conditional operation を提供する: [S3 API](https://developers.cloudflare.com/r2/get-started/s3/)、[互換表](https://developers.cloudflare.com/r2/api/s3/api/)。
- WebP は lossy/lossless と alpha をサポートする: [WebP overview](https://developers.google.com/speed/webp)。

## 公開契約

R2 の object key は Issue 指定どおり安定した `thumb.webp` とする。上書き後に古い edge/browser
cache を参照しないよう、snapshot validator は WebP bytes の SHA-256 を
`thumbUrl?...v=<sha256>` に含める。Worker は query を object key に含めず、`image/webp` を強制し、
GLB と同じ Hunyuan 地域制限を R2 access より前に適用する。縮略図が無い cell は従来どおり
`thumbUrl` を持たないが、存在する縮略図は decode、静止画、320 x 320 の全条件を満たさなければ
manifest を生成しない。

## ライセンス確認

Three.js は [MIT](https://github.com/mrdoob/three.js/blob/dev/LICENSE)、Playwright は
[Apache-2.0](https://github.com/microsoft/playwright/blob/main/LICENSE)、Sharp は
[Apache-2.0](https://github.com/lovell/sharp/blob/main/LICENSE) である。Sharp の配布物が使う
libvips は [LGPL-2.1-or-later](https://github.com/libvips/libvips/blob/master/COPYING)。本リポジトリの
開発用生成ツールとして利用する上で、生成した WebP の公開を妨げる条件は見つからなかった。

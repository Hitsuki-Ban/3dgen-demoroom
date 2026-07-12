# セル単位 viewing orientation 整列方式の調査

- 確認日: 2026-07-13
- 対象: Issue #85
- 対象バージョン: Three.js 0.185.1、Playwright 1.61.1、OpenCV Python wheel 5.0.0.93

## 結論

生成物の GLB は変更せず、`model/task` ごとに **absolute object-local rotation** を記録する。
単位は degree、Euler order は `XYZ` に固定する。セル値がある場合は既存の model-level fix に
加算せず、セル値が最終 viewing rotation として置き換える。補正 OFF は identity、ON は同じ
absolute rotation を再適用する。この単一路径なら TripoSR の pitch/roll を含む場合も回転順が
曖昧にならない。

自動処理は正解を無理に確定するものではなく、候補順位付けとして使う。全成功セルの top 候補を
課題別 contact sheet にし、25 課題すべてを目視確認してから canonical registry に採用する。
対称形や top margin の小さいセルは `ambiguous` とし、manual provenance と理由を残す。

## 実データ上の境界

- matrix は 11 models x 25 tasks = 275 セルだが、成功は 274 セルである。
- `partcrafter/chrome-espresso-machine` は既存 pipeline が要求する expected failure で、GLB がない。
- registry は 275 key を厳密に要求し、274 success は `fixed`、expected failure は
  `excluded: expected-failure-no-glb` とする。GLB のないセルに identity fix を捏造しない。
- reference PNG 25 枚はすべて完全不透明で、透明 alpha を silhouette として利用できない。

## Reference foreground mask

単一色からの距離 threshold は採用しない。reference は浅い灰色の radial gradient を持ち、中央の
背景色が corner と異なるためである。OpenCV GrabCut を rectangle 初期化で実行し、外周を sure
background、内部を unknown として foreground を分離する。固定 recipe は次のとおり。

1. 256 x 256 に area resize
2. 3 px inset rectangle、5 iterations
3. 3 x 3 close/open 各 1 回
4. canvas 0.1% 未満の孤立成分を除去し、0.05% 未満の非接辺 hole だけを充填
5. foreground ratio 0.05–0.85、border foreground < 0.005、最大 component 比率 >= 0.85 を要求

初回全量実行では細長い `medieval-longsword` が 0.056564 で、一般的な 0.08 下限では正しい
foreground を拒否した。実データを確認した上で下限を 0.05 に固定した。これは別処理への fallback
ではなく全 task 共通 recipe の明示的な校正である。

QA を通らない画像で別アルゴリズムへ fallback しない。必要ならその task 用 seed を明示的な
recipe 変更として追加し、report と fingerprint に残す。OpenCV は GUI 不要の headless wheel を
PEP 723 script から `uv` で exact pin して実行する。

## Candidate render と score

既存の pinned Chromium / Three.js thumbnail renderer を使い、1 GLB を 1 page に一度だけ load
する。同じ page で absolute rotation を設定し、2 animation frames 待って透明 PNG を撮影する。
candidate silhouette は PNG alpha から取得する。

各 rotation は model の既存 position/scale を identity に戻してから適用し、その姿勢の world-space
bounds で center と max dimension を再計算する。初期姿勢で一度だけ正規化した後に rotation だけを
変えると、modeling origin が bounds center でない GLB は画面内で漂流するためである。偏離原点の
fixture を 0/90 degree で撮影し、alpha bounds が canvas center に残ることを smoke test する。

reference/candidate mask は foreground bounding box の縦横比を保って正方形へ正規化する。
初期 score は以下の輪郭中心の値とする。

```text
score = 0.55 * mask IoU
      + 0.30 * tolerant edge F1
      + 0.15 * 4x4 spatial occupancy similarity
```

材質、lighting、geometry-only model の差が大きいため、global color histogram は主 score に
入れない。top margin が 0.025 未満なら自動確定せず ambiguous とする。数値は最終的な品質保証
ではなく候補順位付けの evidence であり、contact-sheet review は省略しない。

通常モデルは yaw を 15 degree 刻みで全周探索する。課題依存の pitch/roll 崩れが確認された
TripoSR と一部 3DTopia-XL は pitch/roll `-90,-45,0,45,90` と yaw 30 degree の粗い SO(3)
grid を使う。候補は canonical range `[-180, 180)` に正規化し、同一 rotation を重複させない。

## Rotation contract の根拠

Three.js の Euler は axis order を持ち、既定 order は `XYZ` である。`Object3D.rotation` は local
Euler、実際の回転状態は quaternion と同期し、`setRotationFromEuler` / `setRotationFromQuaternion`
は現在値への delta ではなく回転を設定する API である。Euler の加算は採用せず、search と runtime
の双方が同じ absolute `XYZ` 値を設定する。

canonical JSON は人がレビュー・修正しやすい degree Euler を正本とする。runtime では Three.js
が quaternion へ変換する。将来 quaternion を schema に併記する互換形式は作らず、必要になった
時点で schema version を更新する。

## Thumbnail publish contract

orientation registry、mask recipe、score/search recipe の hash を thumbnail render fingerprint に
含める。orientation 変更後は 274 WebP を conditional PUT し、独立 `--check` で fresh を確認する。
その後 manifest を再生成して `thumbUrl?v=<sha256>` を更新しなければ、安定 object key 上の古い
browser/edge cache を回避できない。

最終値の audit は gitignored の画像/report に依存させない。selected evidence ledger に全 cell の
rank、rotation、score components、source GLB identity、reference mask hash、provenance と full report
hash を保存し、canonical registry はその ledger だけから fail-fast で再生成する。

## 参照資料

- OpenCV GrabCut tutorial / API: <https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html>, <https://docs.opencv.org/4.x/d3/d47/group__imgproc__segmentation.html>
- GrabCut original paper (Rother, Kolmogorov, Blake, 2004): <https://doi.org/10.1145/1015706.1015720>
- OpenCV morphology: <https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html>
- OpenCV distance transform: <https://docs.opencv.org/4.x/d7/d1b/group__imgproc__misc.html>
- OpenCV Canny: <https://docs.opencv.org/4.x/da/d22/tutorial_py_canny.html>
- Three.js Euler: <https://threejs.org/docs/pages/Euler.html>
- Three.js Quaternion: <https://threejs.org/docs/pages/Quaternion.html>
- Three.js Object3D rotation setters: <https://threejs.org/docs/pages/Object3D.html>
- Three.js matrix/rotation manual (Euler gimbal lock と quaternion storage): <https://threejs.org/manual/en/matrix-transformations.html>
- OpenCV headless wheel metadata (5.0.0.93): <https://pypi.org/project/opencv-python-headless/>

すべて 2026-07-13 に再確認した。

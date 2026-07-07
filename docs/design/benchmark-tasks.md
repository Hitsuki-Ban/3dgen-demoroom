# ベンチマーク課題セット設計 v1(確定版)

- 作成日: 2026-07-07 / 確定: 2026-07-08
- 作成者: Fable
- ステータス: **確定** — モデルラインナップは `docs/research/models-merged.md`(11 モデル)を参照

## 1. 設計方針

想定読者はゲームグラフィックス開発者。「きれいなデモ」ではなく、**実際のゲームアセット制作で問題になる箇所**を意図的に突く課題セットにする。

- 各課題は **正準テキストプロンプト(英語)+ 正準リファレンス画像 1 枚** のペア。image-to-3D モデルには画像を、text-to-3D モデルにはプロンプトを入力する。リファレンス画像はプロンプトから生成するため、両モダリティの結果を(注意書き付きで)同じ行で比較できる
- 全モデル共通の入力・共通の実行プロトコル(§4)で生成し、チェリーピックの余地を仕様で潰す
- 課題ごとに「何を検証するか(probe)」を明示し、サイト上でもその観点を表示する

## 2. 課題一覧(20 課題)

難易度: ★ = ベースライン / ★★ = 実用ライン / ★★★ = 既知の弱点を突く

| # | id | カテゴリ | プロンプト(正準・EN) | 検証ポイント | 難易度 |
|---|---|---|---|---|---|
| 1 | `cartoon-apple` | 有機・基礎 | A stylized cartoon red apple with a green leaf on the stem, smooth glossy surface | ベースライン検証。滑らかなシェーディング、単純形状の破綻有無 | ★ |
| 2 | `crusty-bread-loaf` | 有機・食品 | A rustic crusty bread loaf with flour dusting and deep score marks on top | 高周波の有機テクスチャ、albedo とジオメトリの分離 | ★ |
| 3 | `scifi-supply-crate` | ハードサーフェス小物 | A weathered sci-fi military supply crate with a glowing orange status panel, worn metal edges and stenciled markings | PBR(金属/粗さ)、エッジのシャープさ、ステンシル文字の再現 | ★ |
| 4 | `ornate-treasure-chest` | 小物 | An ornate fantasy treasure chest with gold filigree, dark oak wood and iron bands, lid slightly open with gold coins spilling out | 複合素材、開口部の内部ジオメトリ、細部パーツ | ★★ |
| 5 | `medieval-longsword` | 武器 | A medieval longsword with an engraved steel blade, leather-wrapped grip and bronze crossguard, standing upright | 細長い形状、左右対称性、彫刻ディテール | ★★ |
| 6 | `plasma-rifle` | 武器 | A bulky sci-fi plasma rifle with glowing cyan energy cells, matte black polymer body and metallic rails | 複雑なハードサーフェス構成、エミッシブ、パーツ分離のしやすさ | ★★ |
| 7 | `victorian-street-lamp` | 小物・構造 | A Victorian cast-iron street lamp with a frosted glass lantern and ornate scrollwork, lit warm glow | 細い垂直構造、ガラス、エミッシブ | ★★ |
| 8 | `wooden-rocking-chair` | 家具 | A wooden rocking chair with thin turned spindles and curved rockers, warm walnut finish | 細い脚・桟のトポロジ破綻(定番の失敗モード) | ★★ |
| 9 | `chrome-espresso-machine` | 素材ストレス | A polished chrome espresso machine with black bakelite handles and a pressure gauge | 鏡面金属の PBR 応答、曲面ハードサーフェス | ★★ |
| 10 | `stained-glass-lantern` | 素材ストレス | A hexagonal stained-glass lantern with colorful translucent panels in a dark bronze frame | 透過・半透明素材の扱い(透過マップ vs ジオメトリ) | ★★★ |
| 11 | `fluffy-monster-plush` | 素材ストレス | A fluffy pastel-blue monster plush toy with stubby horns, button eyes and a stitched smile | ファー/起毛の擬似表現(既知の弱点) | ★★ |
| 12 | `chained-anchor` | トポロジストレス | A heavy iron ship anchor wrapped in a thick chain with interlocking links | 貫通穴・鎖のリンク(genus の高い形状)、繰り返し要素 | ★★★ |
| 13 | `potted-monstera` | 植生 | A monstera plant in a terracotta pot with large split leaves with natural holes | 薄い葉、葉の切れ込み・穴、薄板ジオメトリ | ★★★ |
| 14 | `old-oak-tree` | 植生 | A gnarled old oak tree with twisted branches and dense foliage clumps | 分岐する細い構造、葉群の表現(ビルボード的 vs 実体) | ★★★ |
| 15 | `modular-dungeon-gate` | 建築モジュール | A modular stone dungeon archway with an iron portcullis gate, moss in the crevices | モジュラーアセット的な直線・格子、貫通構造、直角の維持 | ★★ |
| 16 | `arcade-cabinet` | 文字・デカール | A retro 1980s arcade cabinet with colorful marquee art, a CRT screen and a joystick panel | 平面+スクリーン画像+文字の忠実度、凹み(操作パネル) | ★★ |
| 17 | `stylized-hover-bike` | 乗り物 | A stylized sci-fi hover bike with a sleek aerodynamic body, exposed turbine and neon underglow | 複雑なシルエット、閉じた空洞、スタイライズ形状 | ★★★ |
| 18 | `rusty-pickup-truck` | 乗り物 | A rusty 1950s pickup truck with faded teal paint, a cracked windshield and a wooden cargo bed | ガラス、ホイールアーチ等の空洞、リアル系 PBR の経年表現 | ★★★ |
| 19 | `toon-knight-character` | キャラクター | A chibi-style cartoon knight character in full plate armor, standing in a neutral pose, big head and small body | キャラクター比率、四肢・顔の破綻、スタイライズの維持 | ★★★ |
| 20 | `forest-goblin-creature` | クリーチャー | A hunched forest goblin creature with mottled green skin, large pointed ears and tattered cloth garments | 有機的な非対称形状、皮膚テクスチャ、布との複合 | ★★★ |

カテゴリ内訳: 有機 2 / ハードサーフェス小物・家具 5 / 武器 2 / 素材ストレス 3 / トポロジ・植生 3 / 建築 1 / 文字 1 / 乗り物 2 / キャラ・クリーチャー 2。スタイライズ系とリアル系はほぼ半々。

## 3. リファレンス画像仕様

image-to-3D モデルの学習分布に合わせ、全課題で統一する:

- 解像度 **1024×1024**、PNG
- **単一オブジェクト、画面中央**、周囲に 10〜15% のマージン
- 背景は**無地のライトグレー**(#E8E8E8 目安)。透過ではなく塗りつぶし
- カメラは **3/4 ビュー(前方斜め、やや見下ろし)**
- **柔らかい均一照明**。強い影・被写界深度・モーションブラー禁止
- 生成に使ったモデル名・プロンプト・シード・日付を課題メタデータに記録する(出所の追跡可能性)

リファレンス画像の生成は Codex に発注する(別 Issue、確定版になってから)。

## 4. 実行プロトコル

公平性の担保。全モデル共通:

1. **基準環境**: RTX 5090 (32GB) を目標に段階ゲート方式(`docs/research/gpu-rental-merged.md` 参照)。互換性・OOM で不可能なモデルのみ 4090 / A100 80GB を使い、その旨をメタデータと画面に明記。速度比較は同一 GPU 種内のみ
2. **設定は各リポジトリの公式推奨デフォルト**を使う。個別チューニングはしない。使った全パラメータを記録
3. **シード固定で 1 課題 × 1 回生成(N=1)**。予算($20 スタート)を優先した決定。生成ばらつきの展示は、予算に余裕が出た場合に注目課題のみ N=3 で第 2 弾として追加する。失敗(クラッシュ・空出力)はリトライとしてカウントし、回数を記録
4. **手動修正は一切しない**。エクスポート(GLB 化)と共通最適化パイプライン(meshopt/KTX2、全モデル同一設定)のみ通す。**raw 出力も保存**し、サイトには最適化前後のサイズを併記
5. 記録するメタデータ(JSON、スキーマは実装 Issue で確定): モデル名/コミットハッシュ/重みバージョン、GPU、生成時間(wall-clock)、ピーク VRAM、シード、全パラメータ、三角形数・頂点数、テクスチャ枚数と解像度、ファイルサイズ(raw / 最適化後)、リトライ回数

## 5. サイト表示との対応

- 課題ページ: リファレンス画像+プロンプトを左に、各モデルの出力ビューアを横並びで表示。カメラ同期
- 各ビューアに: 三角形数 / 生成時間 / ファイルサイズ / ライセンスバッジ(例: Hunyuan3D の地域条項)
- 「検証ポイント」をキャプションとして表示し、どこを見るべきかを読者に案内する

## 6. 決定事項(2026-07-08 確定)

- **シード数 N=1**: 予算 $20 スタートのため。分散展示(注目課題のみ N=3)は予算次第で第 2 弾
- **キャラクター課題の T-pose 指定は入れない**: プロンプトの "neutral pose" のまま。ポーズの乱れ自体が検証ポイントの一部
- **サイト言語は日本語ファースト**(オーナー・主読者層が日本)。英語版は構造だけ i18n 対応にしておき、コンテンツ翻訳は後日
- **Hunyuan3D 2.1 の成果物**は geo 制限パス(`/restricted/hunyuan3d-21/`)配下に置く(`models-merged.md` 参照)
- text-to-3D と image-to-3D の注意書き文言はフロントエンド実装時に確定(注意書きの存在自体は確定)

# 3DGen DemoRoom

オープンソースの 3D 生成モデル(text/image-to-3D)を**同一の 25 課題・公式デフォルト設定・固定シード**でベンチマークし、生成メッシュそのものをブラウザの 3D ビューアで見比べられる公開展示室。

**▶ 展示サイト: https://3dgen-demoroom.houtei-ban.workers.dev**

**想定読者:** ゲームグラフィックスの開発者。テキスト・画像リファレンスからの 3D アセット生成が「いま実際にどこまでできるのか」を、デモ映像やチェリーピックではなく**無修正の実測データ**で判断できる場を目指しています。

## 実測サマリ(2026-07-11 時点)

| モデル | 成功 | 平均生成時間 | 最長 | 最大 VRAM | 実行 GPU | 出力 |
|---|---|---|---|---|---|---|
| [TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 25/25 | **19.7s** | 71.6s | 7.4 GiB | RTX 4070 Ti | textured |
| [Stable Fast 3D](https://github.com/Stability-AI/stable-fast-3d) | 25/25 | **11.6s** | 59.9s | 7.7 GiB | RTX 4090 | textured, UV 展開済み |
| [TripoSG](https://github.com/VAST-AI-Research/TripoSG) | 25/25 | 19.0s | 59.9s | 11.8 GiB | RTX 4090 | geometry のみ |
| [PartCrafter](https://github.com/wgsxm/PartCrafter) | 24/25 | 49.9s | 83.1s | 16.2 GiB | RTX 4090 | **パーツ分離** mesh |
| [TRELLIS v1](https://github.com/microsoft/TRELLIS) | 25/25 | 47.0s | 79.5s | 19.6 GiB | RTX 4090 | textured |
| [3DTopia-XL](https://github.com/3DTopia/3DTopia-XL) | 25/25 | 76.4s | 114.4s | 10.0 GiB | RTX 4090 | PBR |
| [Direct3D-S2](https://github.com/DreamTechAI/Direct3D-S2) | 25/25 | 140.1s | 236.4s | 30.6 GiB | RTX 5090 | geometry のみ(高解像度) |
| [TRELLIS.2-4B](https://github.com/microsoft/TRELLIS.2) | 25/25 | 281.0s | 1380.2s | 33.1 GiB | RTX 5090 ※1 | PBR |
| [Pixal3D](https://github.com/TencentARC/Pixal3D) | 23/25 ※2 | 331.8s | 501.1s | **45.9 GiB** | RTX 6000 Ada 48GB | textured |
| Step1X-3D | ベンチ実行中 | – | – | –(5090 では texture 段が OOM) | – | textured |
| Hunyuan3D 2.1 | ベンチ実行中 | – | – | – | –(非 EU DC 限定 ※3) | PBR |

- ※1 1 課題のみ 32GB で OOM し、**設定を変えずに** 96GB GPU(RTX PRO 6000 Blackwell)で再実行して成功
- ※2 2 課題は公式 1536 設定の後処理(メッシュ簡略化)で 48GB でも OOM。プロトコル上、低 VRAM モードへのフォールバックは行わず**失敗として記録・公開**
- ※3 ライセンス上 EU / 英国 / 韓国での実行・表示が許諾されないため(下記「ライセンスと地域制限」)

**読み方の注意:**

- 実行 GPU はモデルごとに異なります(そのモデルが動く最小クラスに寄せる方針)。**モデル間の生成時間の直接比較は同一 GPU のもの同士で**。VRAM 要求そのものが本ベンチの主要な測定項目です
- 「最長」が平均から跳ねているのは、各モデルの初回タスクに重みロード等の初期化が含まれるためです
- 生成時間・VRAM・ポリゴン数・使用パラメータなどの全メタデータは、サイト上の各結果および `meta.json` でそのまま公開しています

## ベンチマーク設計

- **25 課題** = 標準 20(有機物・ハードサーフェス・素材ストレス・トポロジストレス・植生・建築・文字/デカール など)+ **アニメ調トラック 5**(セルルック。ゲーム用途を意識)
- 各課題は同一のリファレンス画像(1024²、単色背景)+ 正準英語プロンプトで全モデルに与えられます
- **プロトコル**(詳細: [docs/design/benchmark-tasks.md](docs/design/benchmark-tasks.md)):
  - 各モデルの**公式デフォルト設定のみ**(品質チューニングなし、低 VRAM モード等へのフォールバックなし)
  - 固定シード `20260708`、各課題 1 回のみ(N=1)、手修正なし
  - OOM 等の失敗も `failure.json` としてそのまま公開(失敗の傾向自体が比較情報)
  - 同一パラメータのままの再試行と、同一設定のまま GPU だけ大きくする再実行は許容(`retry_count` として記録)

## 再現性

- 各モデルはコード commit / 重み revision を**ピン留め**した Docker イメージで実行(digest は [docs/runs/](docs/runs/) の実行レポートに記録)
- 決定的な生成になるモデルでは、独立した 2 回の実行でバイト一致の GLB が得られることを確認済み
- 取得時点のライセンス原文を成果物に同梱(`LICENSES.txt`)

## ライセンスと地域制限

生成モデルのライセンスは実務上の採用判断に直結するため、本ベンチの展示対象そのものです:

- モデルごとのコード / 重みライセンスと条件は[モデル選定ドキュメント](docs/research/models-merged.md)に一次ソース付きで整理
- **Hunyuan3D 2.1** は Community License 5(c) により EU・英国・韓国での Output の使用・表示が許諾されないため、当該地域からのアクセスには生成物を配信せず **HTTP 451** とライセンス解説を返します(サイトの実装ごと公開しています: [web/src/worker.ts](web/src/worker.ts))
- **Stable Fast 3D** は Stability Community License(商用は登録制、年商 $1M 超は Enterprise 要)
- 非商用ライセンスの補助重み(背景除去モデル等)を含む Docker イメージは公開していません

## 仕組み

```
tasks/(25課題・リファレンス画像)
  └→ models/<model>/(ピン留め Docker)── RunPod レンタル GPU で実行
        └→ 成果物 + meta.json を R2 へ逐次アップロード
              └→ GitHub Actions で同期・ビルド → Cloudflare Workers でサイト配信
                    (GLB は Worker 経由で R2 から直接ストリーミング)
```

- ビューアは Three.js。単一 WebGL コンテキストのシザービューポートで複数モデルを同時表示し、カメラ同期・PBR / ワイヤーフレーム / matcap / 法線 / UV チェッカー表示を切り替えられます
- ここまでのレンタル GPU 総支出は**約 $14**(9 モデル× 25 課題、失敗試行・ステージング込み。1 モデルはローカル GPU で $0)。実行ごとの内訳は [docs/runs/](docs/runs/) を参照

## リポジトリ構成

| パス | 内容 |
|---|---|
| [`tasks/`](tasks/) | 25 課題の定義とリファレンス画像 |
| [`models/`](models/) | モデルごとの Dockerfile / runner(ピン留め済み) |
| [`bench/`](bench/) | 実行ハーネス(uv / Python)。タスク検証・メタデータ契約・RunPod 起動・R2 アップロード |
| [`web/`](web/) | 展示サイト(Vite + React + Three.js + Tailwind) |
| [`docs/design/`](docs/design/) | ベンチマーク設計・実行プロトコル |
| [`docs/research/`](docs/research/) | モデル選定・GPU レンタル・ホスティングの調査記録(二重調査の突き合わせ形式) |
| [`docs/runs/`](docs/runs/) | クラウド実行レポート(コスト・イメージ digest・失敗の記録) |

## 運営について

このリポジトリは AI エージェント 2 体(Fable / Codex)+人間オーナー 1 名で運営されています(分担・レビュー体制は [AGENTS.md](AGENTS.md))。サイト上の 3D モデルはすべて AI 生成物であり、その旨をサイトにも明記しています。

リポジトリ自体のコードは [MIT License](LICENSE)。各生成モデルとその出力のライセンスはそれぞれのモデルの条件に従います。

# 3DGen DemoRoom

オープンソースの 3D 生成モデル(text/image-to-3D)11 種を**同一の 25 課題・公式デフォルト設定・固定シード**でベンチマークし、生成メッシュそのものをブラウザで見比べられる公開展示室。

### ▶ [展示サイトを開く](https://3dgen.hitsuki.space)

<!-- TODO(screenshot-tool): サイトのヒーロースクリーンショット(ギャラリー+3ペイン比較)をここに挿入 -->

生成時間・VRAM・ポリゴン数・使用パラメータ・**失敗を含む**全実測データを無修正で公開しています。想定読者はゲームグラフィックスの開発者 —「いま実際にどこまでできるのか」をデモ映像ではなく実物のメッシュで判断するための場です。

## 実測サマリ(全 11 モデル計測完了・2026-07-11)

| モデル | 成功 | 平均生成時間 | 最長 | 最大 VRAM | 実行 GPU | 出力 |
|---|---|---|---|---|---|---|
| [Stable Fast 3D](https://github.com/Stability-AI/stable-fast-3d) | 25/25 | **11.6s** | 59.9s | 7.7 GiB | RTX 4090 | textured, UV 展開済み |
| [TripoSG](https://github.com/VAST-AI-Research/TripoSG) | 25/25 | 19.0s | 59.9s | 11.8 GiB | RTX 4090 | geometry のみ |
| [TripoSR](https://github.com/VAST-AI-Research/TripoSR) | 25/25 | 19.7s | 71.6s | 7.4 GiB | RTX 4070 Ti | textured |
| [TRELLIS v1](https://github.com/microsoft/TRELLIS) | 25/25 | 47.0s | 79.5s | 19.6 GiB | RTX 4090 | textured |
| [PartCrafter](https://github.com/wgsxm/PartCrafter) | 24/25 | 49.9s | 83.1s | 16.2 GiB | RTX 4090 | **パーツ分離** mesh |
| [3DTopia-XL](https://github.com/3DTopia/3DTopia-XL) | 25/25 | 76.4s | 114.4s | 10.0 GiB | RTX 4090 | PBR |
| [Direct3D-S2](https://github.com/DreamTechAI/Direct3D-S2) | 25/25 | 140.1s | 236.4s | 30.6 GiB | RTX 5090 | geometry のみ(高解像度) |
| [Hunyuan3D 2.1](https://github.com/tencent-hunyuan/hunyuan3d-2.1) ※3 | 25/25 | 180.9s | 225.0s | 16.5 GiB | RTX 6000 Ada 48GB | PBR |
| [TRELLIS.2-4B](https://github.com/microsoft/TRELLIS.2) | 25/25 | 281.0s | 1380.2s | 33.1 GiB | RTX 5090 ※1 | PBR |
| [Step1X-3D](https://github.com/stepfun-ai/Step1X-3D) | 25/25 | 323.6s | 543.5s | **64.0 GiB** ※4 | RTX PRO 6000 96GB | textured |
| [Pixal3D](https://github.com/TencentARC/Pixal3D) | 25/25 | 392.0s | 1144.9s | **59.8 GiB** ※2 | RTX 6000 Ada / RTX PRO 6000 96GB | textured |

<sub>※1 — 1 課題のみ 32GB で OOM、**設定を変えずに** 96GB GPU で再実行して成功。 ※2 — 2 課題は公式 1536 設定の後処理が 48GB で OOM。低 VRAM モードへ変更せず、GPU のみ 96GB にした exact-task retry で成功。 ※3 — ライセンス上 EU / 英国 / 韓国では表示不可(後述)。実行も非 EU DC で実施。 ※4 — 公式デフォルトでは 96GB 級 GPU のみで完走可能(32GB / 48GB は texture 段で OOM)。</sub>

**表の読み方:** 実行 GPU はモデルごとに異なります(動作する最小クラスに寄せる方針 — VRAM 要求自体が主要な測定項目)。生成時間の直接比較は同一 GPU 同士で。「最長」は各モデルの初回タスクの重みロードを含みます。

## ベンチの原則

1. 各モデルの**公式デフォルト設定のみ**(チューニングなし・低 VRAM モード等へのフォールバックなし)
2. 固定シード `20260708`・各課題 1 回のみ(N=1、設定不変の OOM retry は注記)・手修正なし
3. OOM 等の**失敗もそのまま公開**(失敗の傾向自体が比較情報)
4. コード commit・重み revision・全パラメータを `meta.json` として成果物と一緒に公開

課題設計(標準 20 + アニメ調 5)と完全なプロトコルは [docs/design/benchmark-tasks.md](docs/design/benchmark-tasks.md)。

## ライセンスについて

生成モデルのライセンスは採用判断に直結するため、本ベンチの展示対象です。要注意の 2 例:

- **Hunyuan3D 2.1** — Community License 5(c) により EU・英国・韓国では Output の使用・表示が許諾されず、当該地域には生成物を配信しません(HTTP 451)
- **Stable Fast 3D** — Stability Community License(商用は登録制、年商 $1M 超は Enterprise 要)

全 11 モデルのライセンス整理(一次ソース付き): [docs/research/models-merged.md](docs/research/models-merged.md)

## もっと詳しく

| | |
|---|---|
| 課題とプロトコル | [docs/design/benchmark-tasks.md](docs/design/benchmark-tasks.md) |
| モデル選定とライセンス | [docs/research/models-merged.md](docs/research/models-merged.md) |
| 仕組み・再現性・コスト | [docs/architecture.md](docs/architecture.md) |
| 実行レポート(GPU 単価・失敗記録) | [docs/runs/](docs/runs/) |

---

<sub>本リポジトリは AI エージェント 2 体+人間オーナー 1 名で運営されており、サイト上の 3D モデルはすべて AI 生成物です。リポジトリのコードは [MIT License](LICENSE)、各モデルとその出力はそれぞれのライセンスに従います。</sub>

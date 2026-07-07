# レンタル GPU サービス比較: 3D 生成バッチベンチ用途

- 確認日: 2026-07-07 JST
- 対象: 6-10 個程度の OSS 3D 生成モデルを、モデルごとに Docker コンテナで起動して 10-30 件生成し、GLB とログを外部オブジェクトストレージへ保存するバッチ用途
- 前提: 8 モデル x 20 課題、1 課題 2-10 分、モデルごとにセットアップ・デバッグ 1 時間
- 重要な注意: GPU レンタル料金と在庫は日次で変わる。下記は確認日時点の公式ページ、公式ドキュメント、または Vast.ai 公式価格 JSON に基づく。

## 結論

本命は **RunPod Pods**。理由は RTX 4090/5090、A100 80GB、H100、L40S を同じ運用面で扱え、Docker テンプレート、API、ネットワークボリューム、秒単位課金、明示的な egress 無料がそろっているため。3D 生成ベンチでは CUDA 拡張のビルド失敗や VRAM 不足で GPU 種を切り替える可能性が高いので、最初の基盤は「安い 5090 だけ」より、同じ手順で A100/H100 へ逃げられることを優先したい。

最安寄りの代替は **Vast.ai verified on-demand**。4090/5090 の価格は最も強く、A100/H100/L40S も安い。ただしホスト品質、帯域課金、Docker image pull、interruptible/on-demand の選択、ローカルストレージの所在に運用品質が左右される。最終ベンチに使うなら `verified=true`、高 reliability、direct port、十分な disk/帯域、on-demand を条件に固定する。

自動化・サーバーレス寄りの代替は **Modal**。Dockerfile/GitHub Actions/Volumes/object storage mount が強く、短いジョブを並列に投げるには扱いやすい。ただし 4090/5090 はなく、A100/H100/L40S の単価は RunPod/Vast より高い。研究 repo の CUDA 拡張が Dockerfile で安定ビルドできた後のジョブ基盤として向く。

VM として安定した A100/H100 が必要な場合は **Lambda Cloud** を fallback にする。4090/5090 はないが、SSH と永続 filesystem で CUDA 拡張のデバッグはしやすい。

**Replicate** は主ベンチ基盤ではなく、既に hosted model がある場合の画質 sanity check 用。**Google Colab Pro/Pro+** は GPU 種、時間、Docker、API 自動化が不安定なので、CI/benchmark pipeline には入れない。

## ワークロード時間と概算費用

生成時間:

- 低ケース: 8 x 20 x 2 分 = 320 分 = 5.33 GPU 時間
- 高ケース: 8 x 20 x 10 分 = 1,600 分 = 26.67 GPU 時間
- セットアップ・デバッグ: 8 モデル x 1 時間 = 8 GPU 時間
- 合計: **13.33-34.67 GPU 時間**

リトライ、image pull、初回コンパイル、手動確認を入れると 20-50% 増えやすい。下表は issue 前提の素の GPU 時間だけで計算した。

| GPU / サービス | 時間単価 | 13.33h | 34.67h | コメント |
|---|---:|---:|---:|---|
| Vast.ai RTX 4090 median | $0.38/h | $5.1 | $13.2 | 公式価格 JSON の verified/on-demand 含む市場中央値。帯域費は offer ごとに確認。 |
| Vast.ai RTX 5090 median | $0.47/h | $6.3 | $16.3 | 5090 統一の最安現実ライン。ただし CUDA 12.8+ 移植リスクあり。 |
| Hyperbolic RTX 4090 starting | $0.30/h | $4.0 | $10.4 | 低価格だが 5090 なし。on-demand API は enterprise contact 表記。 |
| TensorDock RTX 4090 typical | $0.35/h | $4.7 | $12.1 | dashboard でリアルタイム在庫確認が必要。 |
| TensorDock RTX 5090 console listing | $0.67/h | $8.9 | $23.2 | console 側で確認した目安。公開価格ページには常時安定表示されない。 |
| RunPod RTX 4090 | $0.69/h | $9.2 | $23.9 | 安さより運用の簡単さと egress 無料を重視する場合。 |
| RunPod RTX 5090 | $0.99/h | $13.2 | $34.3 | 5090 在庫と CUDA 12.8+ 指定を同一 API で扱える。 |
| RunPod A100 80GB PCIe | $1.39/h | $18.5 | $48.2 | VRAM 80GB fallback の低価格ライン。 |
| RunPod H100 PCIe | $2.89/h | $38.5 | $100.2 | 速度優先。コストは 5090 の約 3 倍。 |
| Modal L40S | $1.95/h | $26.0 | $67.6 | serverless job 化できるなら運用は楽。 |
| Modal A100 80GB | $2.50/h | $33.3 | $86.6 | 秒単位・自動化込みの managed premium。 |
| Lambda A100 40GB | $1.99/h | $26.5 | $69.0 | 40GB なので 80GB 前提モデルには不足する可能性。 |
| Lambda H100 PCIe | $3.29/h | $43.9 | $114.1 | VM fallback。 |
| Replicate L40S | $3.51/h | $46.8 | $121.7 | hosted/API 比較用。raw benchmark 基盤としては高い。 |

## サービス比較

| サービス | 価格シグナル | 支払い・日本個人 | Docker / image | 永続ストレージ | API / CLI / GitHub Actions | プロビジョニング・中断 | egress | この用途での評価 |
|---|---|---|---|---|---|---|---|---|
| [RunPod Pods](https://www.runpod.io/pricing) | 4090 $0.69/h、5090 $0.99/h、A100 80GB PCIe $1.39/h、A100 80GB SXM $1.49/h、L40S $0.99/h、H100 PCIe $2.89/h、H100 SXM $3.29/h | クレジット/デビットカード、crypto。日本個人の明示的制限は未確認。 | Docker Hub/GHCR/ECR 等から custom template。Docker Compose/UDP/Windows は対象外。 | volume disk、network volume。network storage は 1TB 未満 $0.07/GB/月、1TB 超 $0.05/GB/月。 | REST/GraphQL/SDK/`runpodctl`。Pods API で GPU 種、CUDA version、network volume を指定可能。 | on-demand は割り込みなし。ただし stop 後に GPU を解放すると再開時に在庫切れの可能性。 | Pods docs で ingress/egress 無料を明記。 | **本命**。GPU 種の逃げ道、Docker、API、storage、egress のバランスが最もよい。 |
| [Vast.ai](https://vast.ai/pricing) | 公式価格 JSON: 4090 `$0.13 min; $0.35/$0.38/$0.53 p25/median/p90`、5090 `$0.21; $0.40/$0.47/$0.67`、A100 80GB PCIe `$0.40; $0.49/$0.70/$1.00`、H100 SXM `$1.33; $2.00/$2.33/$3.29`、L40S `$0.40; $0.47/$0.53/$0.80` | Stripe card、BitPay/Crypto.com。日本個人の明示的制限は未確認。 | create instance 時に Docker image を指定。template/custom image/registry 対応。 | container storage、local volume、cloud sync。local は物理ホストに紐づく。 | REST API、CLI、Python SDK。search offers で `verified=true`、direct port、reliability 等を条件化可能。 | on-demand と interruptible。marketplace なので host offline、image pull 遅延、性能差に注意。 | offer ごとに upload/download cost。`internet_up_cost_per_tb`、`internet_down_cost_per_tb` を確認。 | **最安代替**。最終ベンチでは verified on-demand の条件固定が必須。 |
| [Modal](https://modal.com/pricing) | H100 $3.95/h、H200 $4.54/h、A100 80GB $2.50/h、A100 40GB $2.10/h、L40S $1.95/h、L4 $0.80/h。CPU/memory も別課金。 | 無料枠/Starter/Team。支払いは dashboard 側で設定。日本個人の明示的制限は未確認。 | `modal.Image.from_dockerfile`、既存 public/private image、Python API で image 定義。 | Modal Volumes $0.09/GiB/月、1TiB/月 transfer included。S3/R2/GCS mount あり。 | Modal CLI/API、GitHub Actions continuous deployment docs あり。job orchestration は強い。 | serverless container。cold start と build cache に注意。 | Volumes transfer allowance あり。外部 bucket mount 利用が現実的。 | **自動化代替**。CUDA repo を Dockerfile 化できた後は扱いやすい。4090/5090 はない。 |
| [Lambda Cloud](https://lambda.ai/pricing) | 1x H100 PCIe $3.29/h、1x H100 SXM $4.29/h、A100 40GB $1.99/h、A10 $1.29/h。8x H100 SXM $3.99/GPU/h。 | dashboard で payment/SSH/API key。日本個人の明示的制限は未確認。 | VM/SSH。Cloud API で base image 選択可。Docker は VM 内で自由に使える。 | persistent filesystems。リージョン単位で作成し API 管理可能。 | Cloud API で instance lifecycle。GitHub Actions から API 呼び出しは現実的。 | VM 型でデバッグしやすい。GPU 在庫はリージョン依存。 | Lambda 側は no egress fees と案内。 | **A100/H100 fallback**。consumer GPU はないが、CUDA 拡張デバッグに強い。 |
| [Replicate](https://replicate.com/pricing) | T4 $0.81/h、L40S $3.51/h、A100 80GB $5.04/h、H100 $5.49/h。public model は runtime 課金、private model は dedicated hardware 課金。 | API billing。日本個人の明示的制限は未確認。 | Cog で model image を build/push。一般 VM ではない。 | Prediction output は短期保存前提。汎用 persistent volume はない。 | HTTP API/CLI。GHA から `cog push` や prediction API は可能。 | hosted inference。研究中の CUDA build/debug には不向き。 | prediction files は retention に注意。 | **hosted model 比較用**。主ベンチ基盤にはしない。 |
| [TensorDock](https://www.tensordock.com/cloud-gpus.html) | 4090 typical $0.35/h。別ページ/console で 5090 $0.67/h、A100 PCIe $1.50/h、A100 SXM4 $1.80/h、H100 SXM5 $2.25/h 目安。 | card 対応。VAT/GST 対象国の consumer 制限記述があり、日本個人は事前確認。 | VM OS template。Docker preinstall や cloud-init での起動は可能だが、RunPod/Vast のような Docker image 直指定とは違う。 | NVMe block storage、Core Compute network storage。 | REST API v2。公式 CLI は確認できず。 | spot beta、standard host の停止リスク、balance 0 で server delete の注意。 | 少なくとも 1Gbps included。明示的な egress 単価は確認できず。 | **低価格候補**。dashboard 確認後に小規模 smoke test したい。 |
| [Hyperbolic](https://www.hyperbolic.ai/marketplace) | marketplace: GPU from $0.20/GPU/h、4090 starting $0.30/h、H100 SXM starting $1.50/h。5090 は確認できず。 | Stripe card、wire/ACH。日本個人の明示的制限は未確認。 | PyTorch/TensorFlow/CUDA image、SSH 後 Docker 実行。 | onboard storage は terminate で消える。persistent volume 100GB-10TB は region/console 確認。 | CLI あり。on-demand public API は enterprise contact の記述。 | provisioning 最大 25 分の記述。on-demand は supply 依存。 | egress 単価未確認。 | **4090 低価格候補**。自動化 API の確認が先。 |
| [Novita AI GPUs](https://novita.ai/gpus) | public page は GPU instance/serverless/custom deployment を確認できるが、安定した SKU 別価格は console 確認が必要。console snippet では H100、4090、5090、CUDA 13.0 filter を確認。 | payment は console 確認。日本個人の明示的制限は未確認。 | one-click template、PyTorch/JAX/CUDA、custom deployment の記述。 | POSIX/object/parallel storage の記述。 | REST/gRPC/Terraform/CLI の記述。 | serverless は scale-to-zero、GPU instance は console 確認。 | 未確認。 | **保留**。価格と egress を owner account で要確認。 |
| [Google Colab](https://colab.research.google.com/signup) / [Colab Enterprise pricing](https://cloud.google.com/colab/pricing) | Pro/Pro+ は compute unit 制。Enterprise GPU hourly は L4 $0.672/h、T4 $0.42/h、A100 $3.52/h、A100 80GB $4.71/h など。 | Google account/支払い。 | Docker/custom image は不可。notebook 前提。 | local disk は ephemeral。Drive/GCS 経由。 | benchmark pipeline としての API/CLI は弱い。 | GPU 種、接続時間、availability が保証されない。 | GCS 等の料金体系に従う。 | **非推奨**。手元検証だけ。 |

## RTX 4090 / 5090 だけに統一するシナリオ

### 価格

8 モデル x 20 課題の前提を consumer GPU だけで回すと、GPU 代はかなり下がる。

| 構成 | 現実的な価格 | 総額目安 | 評価 |
|---|---:|---:|---|
| Vast.ai verified RTX 4090 | median $0.38/h、p90 $0.53/h | median $5.1-$13.2、p90 $7.1-$18.4 | 24GB で足りるモデルに限定できるなら最安クラス。 |
| Hyperbolic RTX 4090 | starting $0.30/h | $4.0-$10.4 | 絶対価格は安いが API/自動化と egress の事前確認が必要。 |
| TensorDock RTX 4090 | typical $0.35/h | $4.7-$12.1 | dashboard 在庫と payment 条件を確認してから。 |
| RunPod RTX 4090 | $0.69/h | $9.2-$23.9 | marketplace リスクを減らし、egress 無料と API を優先するなら妥当。 |
| Vast.ai verified RTX 5090 | median $0.47/h、p90 $0.67/h | median $6.3-$16.3、p90 $8.9-$23.2 | 32GB と低価格は魅力。互換性リスクが最大の論点。 |
| TensorDock RTX 5090 | console listing $0.67/h | $8.9-$23.2 | 価格表示の安定性を dashboard で要確認。 |
| RunPod RTX 5090 | $0.99/h | $13.2-$34.3 | 5090 運用を API/volume/egress 込みで安定させたい場合。 |

A100/H100 を全く使わない場合、素の GPU 代は **$4-$35 程度**に収まる。ただしこの数字は「全モデルが 4090/5090 で一発で通る」前提で、CUDA 拡張の移植、失敗リトライ、別 GPU fallback の人件費を含まない。

### RTX 5090 の互換性リスク

RTX 5090 は NVIDIA 公式 compute capability 表で Blackwell 世代の **compute capability 12.0 (`sm_120`)**。4090 は Ada の `sm_89` で、A100 は `sm_80`、H100/H200 は `sm_90` なので、5090 は研究 repo の古い CUDA 前提と相性が違う。

確認日時点の実務リスク:

| 項目 | 判断 | ベンチへの影響 |
|---|---|---|
| CUDA Toolkit | CUDA 12.8 以降が `sm_120` の実質基線。 | CUDA 11.8/12.1 固定の Dockerfile は 5090 で失敗しやすい。 |
| PyTorch | PyTorch 2.7.0 + CUDA 12.8 wheel 以降が安定基線。 | torch 2.1/2.2 + cu118/cu121 固定 repo は `sm_120 is not compatible` や `no kernel image` になりやすい。 |
| flash-attn | Ampere/Ada/Hopper 前提の wheel や source build が多く、SM120 issue が残る。 | まず PyTorch SDPA/cuDNN fallback で動かし、flash-attn は検証済み wheel/fork がある時だけ有効化する。 |
| xFormers | 新しめの wheel は改善しているが、RTX 5090 half attention failure 報告あり。 | 旧版 pin は避け、attention backend をログに残す。 |
| spconv / SparseConv | Blackwell/cu128 対応 issue が残る。 | sparse conv 系 repo は 5090 初回ベンチに入れる前に単体 smoke test が必要。 |
| nvdiffrast | PyTorch/CUDA version matching が必要。RTX 5090 で CUDA error 700 報告あり。 | source rebuild と rasterization smoke test が必須。install 成功だけでは合格にしない。 |

5090 を使う場合の最低条件:

- Docker image は CUDA 12.8+ と `torch>=2.7` の CUDA wheel を明示する。
- 自前 CUDA extension は `TORCH_CUDA_ARCH_LIST="8.9 12.0"`、または 5090 専用なら `12.0` を明示する。
- `torch.__version__`、`torch.version.cuda`、`torch.cuda.get_arch_list()`、NVIDIA driver、CUDA toolkit、attention backend、extension wheel/source commit、peak VRAM を必ずログに残す。
- flash-attn/xFormers/nvdiffrast/spconv は、モデル本番生成の前に 1 prompt smoke test と kernel import test を通す。

### 単一 GPU 種の推奨

**全候補モデルを含めた科学的な再現性**を優先するなら、単一 GPU は A100 80GB が最も安全。24/32GB に落とすと、VRAM 要件の大きいモデルや古い CUDA repo を外すか移植する判断が入り、モデル比較ではなく「consumer GPU で動くモデル比較」になる。

**展示価値として consumer workstation reproducible を優先する**なら、単一 GPU は RTX 5090 32GB。ただし最初から全モデル一括ではなく、下記の gate を置く。

1. TRELLIS / Stable Fast 3D / TripoSR 系の軽量モデルで CUDA 12.8 + torch 2.7+ baseline を作る。
2. nvdiffrast / flash-attn / sparse conv を使う重いモデルで extension smoke test を通す。
3. 32GB peak VRAM を超えるモデル、または 5090 で extension が通らないモデルは consumer-only ベンチから外す。

**4090 単一**はコストと互換性の面で魅力があるが、24GB VRAM が厳しい。TripoSR、Stable Fast 3D、TripoSG、InstantMesh/Unique3D 系など軽量・中量モデル中心の「4090 friendly」ベンチなら成立する。TRELLIS.2、Direct3D-S2 1024、Hunyuan3D 系 texture pipeline などは 24GB で品質設定を落とす可能性がある。

**4090/5090 を混ぜる場合**の現実案:

- 4090: 24GB で通るモデル、古い CUDA/torch pin が強いモデル、低コスト大量 smoke test。
- 5090: 24GB では厳しいが 32GB で通るモデル、CUDA 12.8+ へ移植済みのモデル、最終 consumer showcase。
- A100 80GB: Hunyuan3D 2.1 full texture、32GB 超え、spconv/nvdiffrast/flash-attn が 5090 で詰まった場合の fallback と reference run。

この混在案では、生成時間の公平比較は GPU 種別ごとに分ける。4090 と 5090 で attention backend や CUDA extension が違う場合、速度差は純粋なハード比較として扱わない。

## 推奨セットアップ手順

### RunPod Pods

オーナーに依頼する初期作業:

1. [RunPod](https://www.runpod.io/) アカウントを作成する。
2. Billing でクレジットカードを登録し、必要なら最小限のクレジットを入れる。
3. Settings / API Keys で API key を発行する。
4. Storage で benchmark 用 network volume を作る。GLB の最終保存先は Cloudflare R2 など外部 object storage にし、volume は cache/build 用にする。
5. Template を作成し、GHCR/Docker Hub の benchmark image を指定する。最初は `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04` 系からモデル別 image を作る想定。
6. Pods API で `gpuTypeIds`、`allowedCudaVersions`、`networkVolumeId` を指定して起動できることを確認する。
7. GitHub Actions には `RUNPOD_API_KEY`、R2 credentials、benchmark config を secrets として登録する。

運用上の指定:

- 5090 benchmark は `allowedCudaVersions` に CUDA 12.8+ を含める。
- 最終 run は interruptible ではなく on-demand を使う。
- Secure Cloud が選べる場合は優先する。
- Pod stop 後に GPU を解放すると同一 GPU が再確保できないことがあるので、長いベンチ期間中はコストと再現性のトレードオフを明示して運用する。

### Vast.ai

オーナーに依頼する初期作業:

1. [Vast.ai](https://vast.ai/) アカウントを作成する。
2. Billing で card または対応 payment を設定する。
3. API key を発行する。
4. GitHub Actions からは REST API を直接呼ぶか、CLI を使う場合は Python tool として `uv tool install vastai` のようにプロジェクト外へ導入する。
5. Offer search は少なくとも `verified=true`、`rentable=true`、`direct_port_count>=1`、必要 disk、必要 CUDA、十分な reliability を条件にする。
6. `internet_up_cost_per_tb` と `internet_down_cost_per_tb` が高い host は避ける。

例:

```bash
vastai search offers 'gpu_name=RTX_5090 num_gpus=1 verified=true direct_port_count>=1 rentable=true' -o 'dlperf_usd-'
```

運用上の指定:

- 最終 benchmark は interruptible ではなく on-demand。
- 価格だけでなく、reliability、host location、disk bandwidth、image pull 済み template、egress を見る。
- local volume は物理 host に紐づくので、GLB とログは必ず外部 object storage へ同期する。

### Modal

オーナーに依頼する初期作業:

1. [Modal](https://modal.com/) アカウントを作成する。
2. Billing を設定し、workspace を作る。
3. local または CI に Modal token を発行する。
4. Codex/Fable 側では `uv tool install modal` で CLI を入れ、`modal token set` または GitHub Actions secrets で認証する。
5. モデルごとに `modal.Image.from_dockerfile("Dockerfile")` で image を定義し、Volume または Cloud Bucket Mount で input/output を分ける。
6. GitHub Actions から `modal deploy` または `modal run` を呼ぶ。

運用上の指定:

- A100/H100/L40S でよいモデルだけ Modal に載せる。
- 5090 固有の検証には使わない。
- Modal Volumes は cache/output に便利だが、最終成果物は R2/S3/GCS に同期する。

### Lambda Cloud

オーナーに依頼する初期作業:

1. [Lambda Cloud](https://lambda.ai/) アカウントを作成する。
2. Billing、SSH key、API key を設定する。
3. 必要リージョンに persistent filesystem を作る。
4. Cloud API で H100/A100 instance を起動できることを確認する。
5. VM 内で Docker と model image を使って手動 smoke test を行う。
6. GitHub Actions からは Cloud API で instance lifecycle を操作し、SSH か runner script で benchmark を起動する。

運用上の指定:

- A100 40GB と A100 80GB は別物として扱う。80GB 前提モデルを 40GB で妥協実行しない。
- CUDA 拡張が RunPod/Vast/Modal で詰まった時のデバッグ環境として使う。

## Replicate の hosted model 確認

Replicate は GPU レンタルというより model API market に近い。対象モデルの一部は比較用に使える。

| モデル | Replicate 状態 | 用途 |
|---|---|---|
| TRELLIS | [firtoz/trellis](https://replicate.com/firtoz/trellis) が存在。Microsoft 公式ではない。A100 80GB 表記。 | 自前 run の出力と hosted output の sanity check。 |
| TRELLIS.2 | [fishwowater/trellis2](https://replicate.com/fishwowater/trellis2) が存在。 | 新しめモデルの API 比較。ただし権威性は要確認。 |
| Hunyuan3D | [tencent/hunyuan3d-2](https://replicate.com/tencent/hunyuan3d-2)、[tencent/hunyuan3d-2mv](https://replicate.com/tencent/hunyuan3d-2mv/api)、[tencent/hunyuan-3d-3.1](https://replicate.com/tencent/hunyuan-3d-3.1) が存在。 | Tencent hosted の API 品質確認。license/display 条件は別途確認。 |
| TripoSG | [aaronjmars/triposg](https://replicate.com/aaronjmars/triposg) が存在。非公式で利用量は低め。 | 補助比較に留める。 |
| Stable Fast 3D | 信頼できる hosted Replicate は確認できず。 | Hugging Face / Stability AI 側を使う。 |

## ベンチ運用メモ

- モデルごとに Docker image digest、Git commit、CUDA、driver、PyTorch、extension build log を保存する。
- 生成結果は `runs/{model}/{gpu}/{timestamp}/` のように GPU 種を含めた path にする。
- 速度比較は GPU 種別・attention backend・precision・VRAM peak を同じ表に残す。
- marketplace を使う場合、最終報告には host id を直接晒さず、GPU 種、price、verified/reliability、region、bandwidth、driver/CUDA だけを残す。
- R2/S3 への upload は job 終了前に必ず行い、GPU volume を唯一の成果物保管場所にしない。

## 出典 URL

### RunPod

- https://www.runpod.io/pricing
- https://docs.runpod.io/pods/pricing
- https://docs.runpod.io/api-reference/pods/POST/pods
- https://docs.runpod.io/storage/network-volumes
- https://docs.runpod.io/pods/templates/overview
- https://docs.runpod.io/pods/templates/manage-templates

### Vast.ai

- https://vast.ai/pricing
- https://storage.googleapis.com/vast-public-gpu-pricing/gpu-price-history.json
- https://docs.vast.ai/cli/hello-world
- https://docs.vast.ai/api-reference/hello-world
- https://docs.vast.ai/api-reference/creating-instances-with-api
- https://docs.vast.ai/api-reference/search/search-offers
- https://docs.vast.ai/guides/instances/pricing

### Modal

- https://modal.com/pricing
- https://modal.com/docs/guide/gpu
- https://modal.com/docs/guide/existing-images
- https://modal.com/docs/guide/volumes
- https://modal.com/docs/guide/cloud-bucket-mounts
- https://modal.com/docs/guide/continuous-deployment
- https://modal.com/docs/examples/install_flash_attn

### Lambda Cloud

- https://lambda.ai/pricing
- https://docs.lambda.ai/public-cloud/on-demand/
- https://docs.lambda.ai/public-cloud/filesystems/
- https://docs.lambda.ai/public-cloud/console/
- https://docs.lambda.ai/public-cloud/importing-exporting-data/

### Replicate

- https://replicate.com/pricing
- https://replicate.com/docs/guides/build/push-a-model
- https://replicate.com/docs/topics/predictions/data-retention
- https://replicate.com/collections/3d-models
- https://replicate.com/firtoz/trellis
- https://replicate.com/fishwowater/trellis2
- https://replicate.com/tencent/hunyuan3d-2
- https://replicate.com/tencent/hunyuan3d-2mv/api
- https://replicate.com/tencent/hunyuan-3d-3.1
- https://replicate.com/aaronjmars/triposg

### TensorDock / Hyperbolic / Novita / Colab

- https://www.tensordock.com/
- https://www.tensordock.com/cloud-gpus.html
- https://console.tensordock.com/
- https://www.tensordock.com/gpu-4090.html
- https://documenter.getpostman.com/view/20973002/2s8YzMYRDc
- https://www.hyperbolic.ai/marketplace
- https://docs.hyperbolic.xyz/docs/getting-started
- https://www.hyperbolic.ai/docs/general/billing-payments
- https://novita.ai/gpus
- https://novita.ai/gpus-console/explore
- https://cloud.google.com/colab/pricing
- https://colab.research.google.com/signup

### RTX 5090 / CUDA 互換性

- https://developer.nvidia.com/cuda/gpus
- https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/
- https://forums.developer.nvidia.com/t/software-migration-guide-for-nvidia-blackwell-rtx-gpus-a-guide-to-cuda-12-8-pytorch-tensorrt-and-llama-cpp/321330
- https://pytorch.org/get-started/locally/
- https://pytorch.org/blog/pytorch-2-7/
- https://pytorch.org/get-started/previous-versions/
- https://discuss.pytorch.org/t/is-there-a-pytorch-build-that-supports-nvidia-rtx-5090-compute-capability-12-0-sm-120/223536
- https://discuss.pytorch.org/t/pytorch-support-for-sm120/216099
- https://github.com/Dao-AILab/flash-attention/issues/1987
- https://github.com/facebookresearch/xformers/issues/1251
- https://github.com/traveller59/spconv/issues/746
- https://nvlabs.github.io/nvdiffrast/
- https://github.com/NVlabs/nvdiffrast/issues/222

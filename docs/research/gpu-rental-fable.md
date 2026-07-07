# レンタルGPUサービス比較(Fable 側)

- 調査日: 2026-07-07
- 調査方法: Claude (Sonnet) リサーチエージェントによる Web 検索・公式ドキュメント確認
- 対をなす Codex 側調査: `gpu-rental-codex.md`(突き合わせ結果は `gpu-rental-merged.md` 予定)

---

## 1. Comparison Table

| Service | RTX 4090 | RTX 5090 | A100 80GB | H100 | L40S | Billing / Japan access | Docker & Storage | API/CLI/GitHub Actions | Cold start / interruption | Egress |
|---|---|---|---|---|---|---|---|---|---|---|
| **RunPod** (Pods) | $0.69/hr Secure, ~$0.34/hr Community | $0.99/hr | $1.39/hr PCIe, $1.49/hr SXM | $2.89/hr PCIe, $3.29/hr SXM | $0.99/hr | Prepaid credit, card (Stripe) or crypto, ~$10 min top-up (recommend $100+ chunks on prepaid cards); no Japan-specific blockers found | Full root Docker on Pods; S3-compatible Network Volumes ($0.07/GB-mo <1TB), container/volume disk $0.10/GB-mo | Official REST API, `runpod` Python SDK, `runpodctl` CLI, community GitHub Action (`runpod/test-runner`); well-documented CI patterns | Pods spin up in ~1 min (image-pull dependent); Spot pods get 5s SIGTERM warning; default $80/hr account spend cap (adjustable) | **$0** — no ingress/egress fees |
| **Vast.ai** (marketplace) | ~$0.30–0.45/hr | ~$0.35–0.50/hr | ~$0.67–1.87/hr (unverified→verified) | ~$0.90–1.87/hr (up to ~$2.50 verified reserved) | not clearly published (est. $0.5–1.0/hr) | Prepaid credit, min ~$5, Stripe card or crypto (BitPay/Crypto.com); no PayPal | Any Docker image via CLI/console; storage/egress billed **per-host**, varies (usually free/near-free) | Official `vastai`/`vast-cli` (PyPI + GitHub), scriptable `create instance`/`destroy instance`; used in autoscaler examples | Boot ~1–5 min; **reliability varies wildly by host** — unverified hosts can vanish without notice (verified/datacenter tier costs more but is much safer for unattended jobs) | Typically free, but host-dependent — must check each listing |
| **Modal** | Not offered | Not offered | $2.50/hr ($0.000694/s) | $3.95/hr ($0.001097/s) | $1.95/hr ($0.000542/s) | $30/mo free credit (Starter), then usage; Team plan $250/mo base; card billing | Custom `Image.from_dockerfile()`/registry images, GPU-attached builds for compiling flash-attn/nvdiffrast; Volumes $0.09/GiB-mo (1TiB free) | Best-in-class: native `modal deploy` GitHub Actions continuous-deployment docs, Python-native SDK, true scale-to-zero | Serverless — no pod to "boot", but each of the 8 heterogeneous model repos must be re-wrapped into Modal's Image/function abstraction (extra glue code vs plain `docker run`) | **$0** — explicitly no egress fees |
| **Lambda Cloud** | Not offered | Not offered | $1.99/hr (40GB)–$2.79/hr (80GB SXM) | $3.29/hr PCIe–$4.29/hr SXM | Not offered | Card billing, postpaid-feeling usage invoicing, tax added | Docker via Lambda Stack image or custom base image through API; persistent "Filesystems" (NFS-style) attached at instance creation, must match region | REST API for create/list/terminate; less automation content/community tooling than RunPod/Vast | Historically capacity-constrained for popular GPUs; on-demand hourly, some reserved tiers have 2-week minimums | Not clearly documented (not a stated differentiator) |
| **Replicate** (hosted models, not raw rental) | n/a | n/a | ~$5.04/hr-equiv (per-sec) | ~$5.49/hr-equiv | ~$3.51/hr-equiv | Card billing, pay-as-you-go per-second of **actual inference only** | No general Docker rental — you either call already-hosted models or package your own via **Cog** (Docker-like spec) | Simple REST API; not really a GitHub-Actions "job launcher" in the sense you need — it's an inference API | None (managed) | N/A (API calls only) |
| **fal.ai** | n/a | n/a | n/a | n/a | n/a | Per-generation credit pricing | Same category as Replicate — hosted models only | REST API | None | N/A |
| **TensorDock** | $0.37/hr on-demand, $0.20/hr spot | Not confirmed | from $0.75/hr | $2.25/hr on-demand, $1.30/hr spot | Not confirmed | Card, start with $5 | Marketplace, similar model to Vast.ai (100+ independent hosts) | Has API; automation docs thinner than RunPod/Vast | Marketplace reliability caveats similar to Vast.ai | Not clearly documented |
| **Hyperbolic** | $0.50/hr | Not offered | $1.80/hr | $3.20/hr | Not offered | Card billing | Docker support exists but less documented for custom CUDA builds | Has API/CLI, smaller community | Not well documented | Not clearly documented |
| **Novita AI** | $0.35/hr on-demand, $0.18 spot, $0.61 dedicated | Not offered | Not clearly listed | $1.70/hr bare-metal, $1.99/hr dedicated | Not offered | Card billing, pay-as-you-go | GPU Instances + Docker; also bundles serverless model APIs | Python SDK exists (image-gen focused), GPU-instance automation less documented | Not well documented | Not clearly documented |
| **Together AI GPU Clusters** | n/a | n/a | n/a | $2.55/hr reserved–$3.49/hr on-demand | n/a | Enterprise-leaning; credits/invoicing | InfiniBand bare-metal clusters — **minimum sizes of 8+ GPUs**, built for multi-node training, not single-GPU batch inference | Good API, but wrong shape for this workload | N/A | Not documented for this use case |
| **Google Colab Pro/Pro+** | n/a | n/a | ~$1.43/hr-equivalent (Pro+ only, via CU burn) | Not offered | Not offered | $9.99–11.99/mo Pro, $49.99/mo Pro+, or pay-as-you-go CUs | **No real Docker/root control** — managed notebook VM only; disqualifying for "custom-compiled extensions" requirement | No CLI/API for headless job launch — not automatable from GitHub Actions | Notebook must stay "open"/connected; not built for headless batch | N/A |
| **Newcomers** (Nebius, DataCrunch, SF Compute, Crusoe, Spheron) | — | — | Spheron $1.07/hr on-demand, $0.60/hr spot | Nebius $2.95/hr ($2.00 reserved), DataCrunch $1.99/hr, SF Compute $1.45/hr, Spheron $1.03/hr spot floor | — | Mostly card billing | Generally full Docker/bare-metal control | APIs exist but far less battle-tested community tooling/docs for solo/individual automation than RunPod or Vast | Pricing is attractive, but maturity/support for a first-time individual Japan-based user is unproven | Not well documented |

**Key structural notes:**

- **Modal and Lambda Cloud do not offer consumer RTX cards at all** — only RunPod and Vast.ai (plus some marketplaces like TensorDock/Novita) cover the full RTX 4090 → H100 range in one account.
- **Together AI's GPU Clusters product is architecturally the wrong shape** for this workload (multi-node, 8+ GPU minimums).
- **Google Colab fails the hard "full Docker control / custom-compiled extensions" requirement** outright.
- **Replicate/fal.ai already host some target models** — `tencent/hunyuan-3d-3.1`, `firtoz/trellis`, `fishwowater/trellis2`, `hyper3d/rodin` are live on Replicate; Hunyuan3D and TRELLIS.2 are on fal.ai too. TripoSG does not appear to be hosted on either. Useful as a **quick reference check**, not as the benchmark engine (no control over code version/hardware/settings — defeats an apples-to-apples benchmark).

---

## 2. Recommendation

**Primary: RunPod (on-demand Pods, Secure Cloud).**

- One of only two providers (with Vast.ai) offering the **entire GPU range needed** (4090/5090/A100/H100/L40S) under one account with **plain `docker run`-style control** (no need to re-architect each model repo into a provider-specific abstraction, unlike Modal).
- **Free data egress** — GLB outputs get pulled off repeatedly across models; RunPod is explicit that ingress/egress are $0.
- **Per-second billing** fits 2–10 minute tasks — no hourly-minimum waste.
- Automation maturity: official Python SDK (`runpod` on PyPI), `runpodctl` CLI, REST API, documented GitHub Actions patterns.
- **S3-compatible Network Volumes** for staging weights/outputs without keeping a GPU pod alive; default per-account spend cap ($80/hr, adjustable down) as a safety net for unattended runs.

**Fallback: Vast.ai**, filtered to **verified/datacenter hosts with reliability ≥ 0.98–0.99**.

- Cheapest raw compute, especially RTX 4090/5090-class (models needing only 24–32GB).
- Same Docker-based workflow, official scriptable CLI (`vast-cli`).
- Use opportunistically when RunPod capacity/pricing is unfavorable, or to shave cost on cheap-tier models where an interrupted run is a cheap retry.
- Do **not** use unverified/home-host listings for unattended automated jobs.

**Worth a look, but not primary:**

- **Modal** — most polished CI/CD story but no consumer GPUs and requires wrapping each heterogeneous repo into its Python `Image`/`@app.function` model — a real setup-time tax.
- **Replicate/fal.ai** — use as a **cheap sanity check** for models already hosted there before investing in Docker setup. Not the benchmark engine itself.
- **Lambda Cloud** — pure A100/H100 fallback; no RTX tier, thinner automation tooling.

---

## 3. RunPod Setup Instructions

1. **Create account**: https://www.runpod.io — sign up with email (or Google/GitHub OAuth), verify email.
2. **Add funds**: *Billing → Add Funds*. Credit card (Visa/Mastercard via Stripe; Japan-issued cards work normally). Deposit **$50–100** to start.
3. **Set a spend safeguard**: lower the default $80/hr spend cap to e.g. $5–10/hr.
4. **Generate an API key**: *Settings → API Keys → Create API Key*. **Shown only once** — store in a password manager and add as a GitHub Actions repository secret `RUNPOD_API_KEY`.
5. **Install tooling** (uv 管理): `uv add runpod` (Python SDK) / `runpodctl` CLI from https://github.com/runpod/runpodctl releases. Auth: `runpodctl config --apiKey <key>`.
6. **Storage**: RunPod Network Volume (S3-compatible, region-locked) or external S3-compatible bucket (Cloudflare R2 が本命 — egress も無料で親和性が高い) with creds passed as env vars/secrets. External bucket = more portable.
7. **Docker images per model**: build & push to Docker Hub/GHCR. Build on CPU machines / free GitHub Actions runners — compiling `flash-attn`/`nvdiffrast` needs the CUDA toolchain + `TORCH_CUDA_ARCH_LIST` but **no physical GPU to compile**. Prebuilt flash-attn wheels also exist.
8. **Smoke-test manually once**: `runpodctl create pod --imageName <image> --gpuType <"NVIDIA A100 80GB PCIe">`, verify run script → GLB+logs → bucket upload, terminate.
9. **GitHub Actions**: secrets (`RUNPOD_API_KEY` + bucket creds), `workflow_dispatch` trigger, matrix over models. **Recommended pattern**: the container self-terminates via RunPod API (`RUNPOD_POD_ID` + scoped key) when its batch finishes — sidesteps GitHub's 6-hour job timeout.

---

## 4. Rough Total Cost Estimate

Assumptions: 8 models × 20 tasks = **160 generation tasks**, 2–10 min GPU time per task, ~1 hour setup/debugging per model on live GPU.

| Scenario | Avg GPU-min/task | Blended $/hr | Generation compute | Setup/debug (8×1h) | Storage (~50GB, 1 mo) | **Total** |
|---|---|---|---|---|---|---|
| Optimistic (mostly 4090/L40S) | 3 min | ~$0.85/hr | ~$6.80 | ~$6.80 | ~$3.50 | **≈ $17** |
| Realistic (mixed tiers, some retries) | 6 min | ~$1.30/hr | ~$20.80 | ~$10.40 | ~$3.50 | **≈ $35** |
| Conservative (A100/H100 heavy, +30% retries) | 10 min | ~$2.00/hr | ~$53→$69 | ~$16 | ~$5 | **≈ $90** |

**Bottom line: roughly $20–90 total**, realistic midpoint **$35–50** — covered by an initial $50–100 deposit. Routing lighter models through Vast.ai could shave another 30–50% off generation compute.

---

## 5. Sources Consulted

- https://www.runpod.io/pricing / https://docs.runpod.io/pods/pricing
- https://docs.runpod.io/storage/s3-api / https://docs.runpod.io/get-started/api-keys / https://docs.runpod.io/accounts-billing/billing
- https://www.runpod.io/blog/manage-runpod-account-funding / https://www.runpod.io/blog/spot-vs-on-demand-instances-runpod
- https://www.runpod.io/articles/guides/integrating-runpod-with-ci-cd-pipelines / https://www.runpod.io/articles/guides/ai-on-a-schedule
- https://github.com/runpod/runpodctl / https://github.com/runpod/runpod-python / https://github.com/runpod/test-runner
- https://docs.runpod.io/serverless/workers/github-integration
- https://vast.ai/pricing / https://vast.ai/pricing/gpu/RTX-4090 / https://vast.ai/pricing/gpu/RTX-5090
- https://docs.vast.ai/documentation/instances/pricing / https://docs.vast.ai/documentation/reference/billing
- https://docs.vast.ai/host/verification-stages / https://docs.vast.ai/guides/instances/docker-environment
- https://github.com/vast-ai/vast-cli / https://github.com/vast-ai/base-image
- https://www.gpunex.com/blog/vast-ai-review-2026/
- https://modal.com/pricing / https://modal.com/docs/guide/cuda / https://modal.com/docs/examples/install_flash_attn
- https://modal.com/docs/guide/custom-container / https://modal.com/docs/guide/continuous-deployment / https://github.com/modal-labs/ci-on-modal
- https://lambda.ai/pricing / https://docs.lambda.ai/public-cloud/on-demand/ / https://docs.lambda.ai/public-cloud/filesystems/
- https://replicate.com/tencent/hunyuan-3d-3.1 / https://replicate.com/collections/3d-models / https://replicate.com/pricing
- https://fal.ai/models/fal-ai/hunyuan3d/v2 / https://fal.ai/3d-models
- https://www.tensordock.com/gpu-h100.html / https://www.tensordock.com/gpu-4090.html / https://gpuperhour.com/providers/tensordock
- https://costbench.com/software/ai-gpu-cloud/hyperbolic/
- https://www.spheron.network/blog/gpu-cloud-pricing-comparison-2026/
- https://www.usagepricing.com/blueprint/novita-ai / https://github.com/novitalabs/python-sdk
- https://www.together.ai/pricing / https://www.together.ai/gpu-clusters / https://docs.together.ai/docs/gpu-clusters-billing
- https://cloud.google.com/colab/pricing / https://colab.research.google.com/signup
- https://docs.nebius.com/compute/resources/pricing / https://nebius.com/prices
- https://www.crusoe.ai/cloud/pricing / https://saturncloud.io/blog/gpu-cloud-comparison-neoclouds-2025/
- https://www.thundercompute.com/blog/nvidia-h100-pricing
- https://github.com/Dao-AILab/flash-attention / https://github.com/mjun0812/flash-attention-prebuild-wheels

**Caveats**: マーケットプレイス系(Vast.ai, TensorDock, Spheron, Novita, Hyperbolic)の価格は需給で変動し、一部はアグリゲータサイト経由の値。方向性の参考とし、サインアップ時に必ずライブ価格を再確認すること。RTX 5090 / L40S の一部数値は推定。

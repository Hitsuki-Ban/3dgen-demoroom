# OSS 3D生成モデル調査(Fable 側)

- 調査日: 2026-07-07
- 調査方法: Claude (Sonnet) リサーチエージェントによる Web 検索・一次ソース確認
- 対をなす Codex 側調査: `models-codex.md`(突き合わせ結果は `models-merged.md` 予定)

---

## 1. Comparison Table

| Model | Org | Repo | Released / Last Update | Input | Output | Code License | Weights License | VRAM (inference) | Runnability | Reputation |
|---|---|---|---|---|---|---|---|---|---|---|
| **TRELLIS** (v1) | Microsoft | [microsoft/TRELLIS](https://github.com/microsoft/TRELLIS) | May 2025 (CVPR'25 Spotlight) | image (+ text ckpt) | mesh, 3DGS, or radiance field; textured GLB | MIT (deps nvdiffrast/nvdiffrec separately licensed) | MIT | ~16GB | HF Space + local Gradio; Linux, CUDA 12.x, flash-attn/nvdiffrast compile pain | Widely used, "previous-gen SOTA," huge community tooling (ComfyUI, Blender addons) |
| **TRELLIS.2-4B** | Microsoft | [microsoft/TRELLIS.2](https://github.com/microsoft/TRELLIS.2) | HF weights Nov 30 2025 / paper Dec 16 2025 | single image | textured mesh, PBR (base color/roughness/metallic/opacity) | MIT | MIT | ≥24GB | HF Space; needs CUDA 12.4, torch 2.6, custom kernels (flash-attn, nvdiffrast, nvdiffrec, cumesh, o-voxel, flexgemm) — heavier dependency chain than v1, no Docker/ComfyUI yet as of writing | Current best fully-open general-purpose image-to-3D; "production-grade," ~20s/asset |
| **Hunyuan3D 2.0** | Tencent | [Tencent-Hunyuan/Hunyuan3D-2](https://github.com/Tencent-Hunyuan/Hunyuan3D-2) | Jan 2025 | image | textured mesh | Tencent Hunyuan3D Community License | Same (restrictive) | ~21–29GB (shape+texture) | HF Space, Docker, community ComfyUI | Strong texture quality baseline, superseded by 2.1 |
| **Hunyuan3D 2.1** | Tencent | [Tencent-Hunyuan/Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1) | Jun 13 2025 | image (text via img-gen) | textured mesh, production PBR | Apache-2.0-style permissive for most code | **Tencent Hunyuan3D 2.1 Community License**: excludes EU/UK/South Korea entirely; >1M MAU requires separate Tencent license; no use to improve competing AI models; no military use | Shape 10GB + Texture 21GB (~29GB combined) | HF Space, Docker folder in repo, community ComfyUI nodes | Community consensus: best open PBR texture quality; reference point for "how good open source got" |
| **Hunyuan3D-Omni** | Tencent | [Tencent-Hunyuan/Hunyuan3D-Omni](https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni) | Sep 25 2025 | image + control (point cloud/voxel/skeleton/bbox) | mesh | Same Hunyuan3D Community License family (License.txt present, same restrictions expected) | Same | ~10GB | HF weights, local Gradio | Niche/controllable-gen add-on to 2.1, useful for precision-controlled asset variants |
| Hunyuan3D 2.5 / 3.0 / PolyGen | Tencent | — | Announced 2025, "3.0" referenced Sept 2025 | image | mesh (claims 1536³ res, clean topology) | **Not open-sourced** — open-source request issue (#111) unanswered as of survey date | N/A | N/A | **Not runnable** — closed weights, demo/API only | Reportedly best Tencent quality but inaccessible to self-host |
| **TripoSR** | Stability AI + Tripo (VAST-AI-Research) | [VAST-AI-Research/TripoSR](https://github.com/VAST-AI-Research/TripoSR) | Mar 2024 | single image | mesh (vertex-colored default; `--bake-texture` for UV texture) | MIT | MIT | ~6GB | HF Space, trivial pip install, ComfyUI-3D-Pack node | Legacy-but-beloved ultra-fast baseline (<0.5s/asset on A100); low geometric fidelity by 2026 standards |
| **TripoSG** | VAST-AI-Research (Tripo) | [VAST-AI-Research/TripoSG](https://github.com/VAST-AI-Research/TripoSG) | Mar 2025 (+ scribble variant Apr 2025) | image (or scribble+text) | mesh only, no texture, GLB | MIT | MIT (HF: VAST-AI/TripoSG) | ~8GB | HF Space, simple pip/requirements, no Docker/ComfyUI official | Praised for very high geometric fidelity/detail, "SOTA rectified-flow shape generation" |
| **TripoSF** | VAST-AI-Research (Tripo) | [VAST-AI-Research/TripoSF](https://github.com/VAST-AI-Research/TripoSF) | Mar 2025 | point cloud / mesh (representation-level, not full img→3D pipeline) | ultra-high-res mesh (up to 1024³, arbitrary topology) | MIT | MIT | ≥12GB (1024³) | No Docker/ComfyUI; more of a research representation library than an end-user pipeline | Strong benchmark numbers (82% CD reduction vs prior) but not a drop-in generator — powers TripoSG-class work |
| **Stable Fast 3D** | Stability AI | [Stability-AI/stable-fast-3d](https://huggingface.co/stabilityai/stable-fast-3d) | Aug 2024 | single image (512×512) | UV-unwrapped textured mesh w/ roughness/metallic | Stability AI Community License | Same — **free ≤$1M annual revenue**, else Enterprise License required | Low (<8GB typical) | HF Space, straightforward install | Fast, game-pipeline-friendly (real UVs), a bit dated geometrically |
| **SPAR3D** | Stability AI | [Stability-AI/stable-point-aware-3d](https://github.com/Stability-AI/stable-point-aware-3d) | Jan 2025 | single image | textured UV mesh + real-time point-cloud editing | Stability AI Community License | Same $1M threshold | Low–moderate | HF Space, Stability API alt. | Notable for interactive point-cloud editing of unseen geometry; solid quality upgrade over SF3D |
| **InstantMesh** | Tencent ARC | [TencentARC/InstantMesh](https://github.com/TencentARC/InstantMesh) | Apr 2024 | single image (sparse multi-view LRM) | mesh, textured | Apache-2.0 | Apache-2.0 | ~8GB (multi-view+LRM) | HF Space, ComfyUI-3D-Pack node | Solid 2024-era LRM baseline, now outclassed on geometry by TripoSG/Hi3DGen |
| **CraftsMan3D** | HKUST-SAIL | [HKUST-SAIL/CraftsMan3D](https://github.com/HKUST-SAIL/CraftsMan3D) | May 2024 | image or text | mesh (OBJ) + interactive geometry refiner, untextured base | MIT | MIT | Refine step runs on a single 3080 (~10GB) | HF Space + Dockerfile provided | Interesting "human-in-the-loop" refinement idea, geometry-only quality now dated |
| **Unique3D** | AiuniAI | [AiuniAI/Unique3D](https://github.com/AiuniAI/Unique3D) | NeurIPS 2024 | single image | textured mesh, high-poly | MIT | MIT | Moderate–high (4-stage pipeline w/ upscaling) | ComfyUI node exists (community), local Gradio | Good texture fidelity for its era, slower multi-stage pipeline, superseded |
| **LGM** | 3DTopia / ashawkey | [3DTopia/LGM](https://github.com/3DTopia/LGM) | ECCV'24 Oral | image or text (via multi-view) | **3D Gaussian Splats** (mesh extraction is lossy/secondary) | MIT | MIT | Low (~5s gen) | HF Space, ComfyUI-3D-Pack node | Good for real-time preview/Gaussians, not ideal if hard mesh requirement — would need GS→mesh conversion step |
| **Step1X-3D** | StepFun | [stepfun-ai/Step1X-3D](https://github.com/stepfun-ai/Step1X-3D) | May 13 2025 (ongoing module releases through Jun 2025) | single image | textured mesh (photorealistic/cartoon/sketch texture styles), GLB | **Apache-2.0** | Apache-2.0 | ~27–29GB combined; ~152s/50 steps | HF Space, Gradio; needs PyTorch3D + Kaolin 0.17 (some install friction), no Docker/ComfyUI yet | Praised for tight geometry/texture alignment; fully open incl. training code |
| **Direct3D-S2** | DreamTech / Nanjing Univ / Fudan | [DreamTechAI/Direct3D-S2](https://github.com/DreamTechAI/Direct3D-S2) | May 27 2025 (NeurIPS'25) | single image | mesh via marching cubes, up to 1024³ | MIT | MIT | ~10GB (512³) / ~24GB (1024³) | HF Space; requires building `torchsparse` from source (dependency friction), Ubuntu 22.04 + CUDA 12.1 pinned | Strong gigascale-resolution results, efficient Spatial Sparse Attention; less turnkey to install |
| **Hi3DGen** | Stable-X (CUHK-Shenzhen / ByteDance Games / Tsinghua AIR) | [Stable-X/Stable3DGen](https://github.com/Stable-X/Stable3DGen) | Mar 2025 (ICCV'25) | single image | mesh, geometry-focused (normal-bridging approach) | MIT (explicitly dropped NVIDIA-licensed deps to enable commercial use) | MIT | ~16GB est. (fine-tuned on TRELLIS-Large backbone) | HF Space; marked **[WIP]** in repo; no Docker/ComfyUI officially (community node exists) | Regarded as best-in-class raw geometric precision among open models |
| **Sparc3D** | Independent (Li Zhihao et al.) | [lizhihao6/Sparc3D](https://github.com/lizhihao6/Sparc3D) | May 2025 (paper) | mesh/image (Sparcubes + Sparconv-VAE) | high-res (1024³) arbitrary-topology surface | **Not specified in repo** — no LICENSE file found | Unclear/unpublished | Unknown | HF Space demo exists, but repo has **no releases, unclear weight availability** — effectively paper/demo stage | Good benchmark numbers on paper, but not yet a practical self-hostable pipeline |
| **PartPacker** | NVIDIA (NVlabs) | [NVlabs/PartPacker](https://github.com/NVlabs/PartPacker) | Jun 2025 | single image | part-separated mesh, each part independently editable | Unclear (no LICENSE at expected path) | **NVIDIA Non-Commercial License** (explicit "ready for non-commercial use," research/academic only) | ~10GB (fp16) | HF Space, ComfyUI fork exists (`smthemex/ComfyUI_PartPacker`, ~12GB) | Novel dual-volume-packing part decomposition; blocked for commercial/public-facing use by license |
| **PartCrafter** | CMU / collaborators (wgsxm) | [wgsxm/PartCrafter](https://github.com/wgsxm/PartCrafter) | Jul 13 2025 (open-sourced), NeurIPS 2025 | single RGB image | **structured/compositional mesh** — multiple separable parts per object, GLB | MIT | MIT | ≥8GB (scales with part/token count) | HF Space (`alexnasa/PartCrafter`), pip install, needs libegl/libglu/pyopengl | Same idea as PartPacker but fully permissive license — the practical choice for part-level generation |
| **3DTopia-XL** | Shanghai AI Lab / 3DTopia | [3DTopia/3DTopia-XL](https://github.com/3DTopia/3DTopia-XL) | Oct 2024 (CVPR'25 Highlight) | text **or** image | PBR mesh (base color/metallic/roughness) via Primitive Diffusion (PrimX repr.) | Apache-2.0 | Apache-2.0 | Moderate; ~5s/asset | GitHub + HF weights, straightforward | One of the few genuinely dual-mode (text+image) permissively-licensed PBR generators |
| **MeshAnything V2** | BUAA (buaacyw) | [buaacyw/MeshAnythingV2](https://github.com/buaacyw/MeshAnythingV2) | ICCV 2025 | point cloud (dense mesh/other model's output as input, i.e. a retopology/tokenization stage) | **artist-style low-poly mesh** (≤1600 faces), autoregressive | **No LICENSE file found in repo** — treat as all-rights-reserved by default | Weights on HF, terms unclear | ~8GB, ~45s/mesh on A6000 | Local Gradio + HF Space; CUDA 11.8/torch 2.1 pinned (older stack); needs flash-attn | Unique "clean game-ready topology" angle — directly relevant to game dev, but license ambiguity blocks safe public display of outputs |
| **LLaMA-Mesh** | NVIDIA (nv-tlabs) | [nv-tlabs/LLaMA-Mesh](https://github.com/nv-tlabs/LLaMA-Mesh) | Nov 18 2024 | text (LLM-native, mesh-as-text) | low-res mesh via LLM token generation | NSCLv1 (non-commercial) | NSCLv1 + Llama 3.1 Community License | Standard 8B LLM VRAM (~16GB+) | HF Space | Conceptually interesting (conversational 3D) but low geometric quality and **non-commercial-only** license |
| CSM Cube (Common Sense Machines) | CSM | — | Ongoing SaaS updates 2025 | image/text/video | parts-based mesh, human-like UVs | **Closed source**, not on GitHub | Closed | N/A (API only) | API/SaaS only | Frequently cited as commercial quality bar; not open — reference-only, not benchmarkable in this exercise |
| Meshy, Rodin (Deemos) | Various | — | Ongoing | image/text | mesh | Closed | Closed | N/A | SaaS/API only | Same as above — commercial comparison points, excluded as not open-source |

---

## 2. Recommended Benchmark Lineup (8 models)

1. **TRELLIS.2-4B (Microsoft)** — MIT, image-to-3D. The best fully-open, actively-maintained general-purpose PBR mesh generator as of mid-2026; fits a single 24–80GB card; this is the model developers should treat as "current open SOTA baseline."

2. **Hunyuan3D 2.1 (Tencent)** — Image-to-3D, best-in-class open texture/PBR fidelity and widely cited as the quality bar other papers benchmark against. License has real restrictions (no EU/UK/South Korea, 1M MAU cap) — include it because it IS the reputational SOTA, but flag the license prominently in the demo/report so devs know they can't deploy outputs from that region without a separate Tencent license.

3. **TripoSG (VAST-AI-Research/Tripo)** — MIT, image-to-3D, geometry-only. Best pure-geometry fidelity in the lineup and trivially runnable (8GB, plain pip install); good foil to Hunyuan3D 2.1 to show the "geometry vs. texture" trade-off different labs optimize for.

4. **Hi3DGen (Stable-X)** — MIT, image-to-3D. Community-regarded top geometric precision via normal-bridging; explicitly re-licensed away from NVIDIA-encumbered deps for clean commercial use — a good "pure geometry SOTA" companion/contrast to TripoSG.

5. **Step1X-3D (StepFun)** — Apache-2.0 (cleanest license of any full-quality lab release), image-to-3D with strong geometry-texture alignment and multiple texture styles (photoreal/cartoon/sketch) — useful to show stylization control relevant to game art direction.

6. **PartCrafter (CMU et al.)** — MIT, image-to-3D, compositional/part-separated mesh output. Directly maps to game-dev needs (separable, editable parts instead of one fused blob) and is the licensing-clean alternative to NVIDIA's non-commercial PartPacker — a genuinely novel capability worth showcasing.

7. **3DTopia-XL (Shanghai AI Lab)** — Apache-2.0, the lineup's true **text-to-3D** representative (most other "text-to-3D" tools are actually text→image→image-to-3D chains) plus native PBR output via Primitive Diffusion; fast (~5s).

8. **TripoSR (Stability/Tripo)** — MIT, image-to-3D. Include as the "speed/cost floor" reference point — sub-second, 6GB VRAM, so viewers can see the quality/speed trade-off against the heavier 2025-era models above. Doubles as a sanity-check baseline since it's the most battle-tested/stable install in the set.

*Optional 9th/10th if time allows:* **SPAR3D (Stability)** for its unique real-time point-cloud-editing UX and clean UV-mapped output (game-pipeline-relevant), and/or **Direct3D-S2** for the highest raw voxel resolution (1024³) if the team wants to stress-test the 80GB card — but budget extra setup time for its from-source `torchsparse` build.

---

## 3. Not Worth Including (and why)

- **Hunyuan3D 2.5 / 3.0 / PolyGen** — announced with better specs but **weights are not open-sourced**; an open GitHub issue asking about this has sat unanswered. Not runnable at all.
- **NVIDIA PartPacker** — same part-level idea as PartCrafter but under **NVIDIA's Non-Commercial License**; outputs can't be publicly displayed/used in a commercial game-dev context. Use PartCrafter instead.
- **Sparc3D** — paper/demo-stage only; no LICENSE file, no GitHub releases, unclear weight distribution. Not practically self-hostable yet — revisit in 6-12 months.
- **LLaMA-Mesh** — interesting "LLM speaks mesh" concept, but non-commercial license (NSCLv1 + Llama 3.1 Community License) and low output resolution/quality relative to diffusion-based approaches. Good talking point, bad benchmark candidate.
- **MeshAnything V2** — genuinely relevant idea (clean, low-poly "artist-style" topology, <1600 faces) but the repo has **no LICENSE file**, so legal status of commercial use/output display is ambiguous — skip until Tencent/BUAA clarifies, or get written confirmation first.
- **TripoSF** — not a standalone generator; it's a shape-representation/reconstruction research library consumed by TripoSG-class pipelines. Not a fair "vs." entry on its own.
- **InstantMesh, CraftsMan3D, Unique3D, LGM** — all solid, permissively-licensed 2024-era work, but geometrically and texturally superseded by the 2025 generation (TRELLIS.2, Hunyuan3D 2.1, TripoSG, Hi3DGen, Step1X-3D). Include only if the team specifically wants a "how far we've come since 2024" historical slide — not needed for a SOTA snapshot.
- **LGM specifically** — outputs 3D Gaussian Splats, not mesh; would need a lossy GS→mesh conversion step to meet the "polygon mesh" requirement, undermining an apples-to-apples GLB comparison.
- **CSM Cube, Meshy, Rodin** — genuinely strong quality, frequently used as the commercial bar in threads/marketing, but **entirely closed-source** (SaaS/API only) — cannot be run on the rented GPU at all, so out of scope for this open-source benchmark by definition.
- **Hunyuan3D 2.0** — fully superseded by 2.1 (same license family, worse texture quality); no reason to run both.
- **Hunyuan3D-Omni** — valuable if the team specifically wants controllable-generation (point cloud/skeleton/bbox conditioning) demos, but it's the same base model/license as 2.1 with an added control layer — not a separate quality data point for a first-pass SOTA survey.

---

## 4. Sources Consulted

- https://github.com/microsoft/TRELLIS
- https://github.com/microsoft/TRELLIS.2
- https://github.com/microsoft/TRELLIS.2/blob/main/README.md
- https://github.com/microsoft/TRELLIS.2/releases
- https://github.com/microsoft/TRELLIS/blob/main/LICENSE
- https://huggingface.co/microsoft/TRELLIS.2-4B
- https://huggingface.co/microsoft/TRELLIS-text-large
- https://huggingface.co/microsoft/TRELLIS-text-xlarge
- https://comfyui-wiki.com/en/news/2025-12-18-microsoft-trellis2-3d-generation
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/LICENSE
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/issues/111
- https://github.com/Tencent-Hunyuan/Hunyuan3D-Omni
- https://x.com/TencentHunyuan/status/1971495031040283125
- https://github.com/VAST-AI-Research/TripoSG
- https://github.com/VAST-AI-Research/TripoSF
- https://github.com/VAST-AI-Research/TripoSR
- https://github.com/VAST-AI-Research/TripoSR/blob/main/README.md
- https://github.com/VAST-AI-Research/TripoSR/blob/main/LICENSE
- https://huggingface.co/VAST-AI/TripoSG
- https://www.tripo3d.ai/blog/vast-open-source-month
- https://huggingface.co/stabilityai/stable-point-aware-3d
- https://github.com/Stability-AI/stable-point-aware-3d/blob/main/LICENSE.md
- https://stability.ai/news/stable-point-aware-3d
- https://huggingface.co/stabilityai/stable-fast-3d
- https://github.com/stepfun-ai/Step1X-3D
- https://github.com/stepfun-ai/Step1X-3D/blob/main/README.md
- https://comfyui-wiki.com/en/news/2025-05-23-stepfun-step1x-3d-open-source-3d-generation
- https://github.com/DreamTechAI/Direct3D-S2
- https://huggingface.co/papers/2505.17412
- https://github.com/Stable-X/Stable3DGen
- https://github.com/Stable-X/Stable3DGen/blob/main/README.md
- https://arxiv.org/abs/2503.22236
- https://github.com/lizhihao6/Sparc3D
- https://arxiv.org/abs/2505.14521
- https://github.com/NVlabs/PartPacker
- https://huggingface.co/nvidia/PartPacker
- https://github.com/smthemex/ComfyUI_PartPacker
- https://github.com/wgsxm/PartCrafter
- https://huggingface.co/spaces/alexnasa/PartCrafter
- https://github.com/3DTopia/3DTopia-XL
- https://huggingface.co/3DTopia/3DTopia-XL
- https://github.com/3DTopia/LGM
- https://huggingface.co/ashawkey/LGM
- https://github.com/TencentARC/InstantMesh
- https://github.com/TencentARC/InstantMesh/blob/main/LICENSE
- https://github.com/HKUST-SAIL/CraftsMan3D
- https://github.com/AiuniAI/Unique3D
- https://github.com/buaacyw/MeshAnythingV2
- https://github.com/nv-tlabs/LLaMA-Mesh
- https://github.com/MrForExample/ComfyUI-3D-Pack
- https://www.3daistudio.com/state-of-ai-3d-generation-2026
- https://x.com/CSM_ai/status/1947821170377589195
- https://ai.meta.com/blog/segment-anything-common-sense-machines-3d-assets/

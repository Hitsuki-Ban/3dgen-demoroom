# 2026-07 Cloud Wave 2

Checked: 2026-07-09
Issue: #37

## Status

Batch A and `direct3d-s2` have completed and have been published to the public site-data prefixes in R2.
The remaining Batch B/C models stay in scope for the same issue/PR.

- Active RunPod pods after the `direct3d-s2` publish: `[]`
- RunPod balance after the 3DTopia-XL publish check: `$16.2145592614`
- Current RunPod token can use REST Pods and Billing endpoints, but GraphQL `myself.clientBalance` returns HTTP 403 `error code: 1010`; `direct3d-s2` launch used REST create with active-pod and billing checks instead of `bench-harness runpod-launch`'s GraphQL balance gate.
- RunPod reported the EU-RO-1 RTX 4090 runtime price as `$0.69/hr` during the paid runs, higher than the `$0.34/hr` value captured in the issue text.
- RunPod reported the EU-RO-1 RTX 5090 runtime price as `$0.99/hr` during `direct3d-s2` staging, smoke, and full runs.
- EU-RO-1 network volume `wnqijpazd5` was expanded from 30GB to 80GB for wave 2 staging.
- Wave 2 staging validation report: `runs/staging/20260709T005450Z/network-volume-wnqijpazd5-wave2-batch-a-validate.json`
- Direct3D-S2 staging validation report: `runs/staging/20260709T090135Z/network-volume-wnqijpazd5-direct3d-s2-v2-fast.json`
- Step1X-3D main weights staging report: `runs/staging/20260709T131830Z/network-volume-wnqijpazd5-step1x-3d-v1.json`
- Step1X-3D external HF cache reports:
  - `runs/staging/20260709T135531Z/network-volume-wnqijpazd5-step1x-dinov2-cache-v3-cpu.json`
  - `runs/staging/20260709T141027Z/network-volume-wnqijpazd5-step1x-texture-deps-v1-cpu.json`
- Staged Batch A payloads included:
  - `/workspace/weights/TRELLIS-image-large/`
  - `/workspace/weights/3DTopia-XL/`
  - `/workspace/torch/hub/checkpoints/dinov2_vitl14_reg4_pretrain.pth`
  - `/workspace/torch/hub/checkpoints/dinov2_vitb14_reg4_pretrain.pth`
  - `/workspace/weights/rembg/u2net.onnx`

## Runtime Images

| Model | Image | Digest | Notes |
| --- | --- | --- | --- |
| TRELLIS v1 | `ghcr.io/hitsuki-ban/3dgen-trellis1-runtime:2026-07-cloud-wave2-batch-a` | `sha256:0326602fb7daf9e04dc3e168e919b8e7672db4299f96d16a7c7b42c700c3a385` | Uses `SPCONV_ALGO=native`; the earlier `auto` path failed with `SIGFPE` on RTX 4090. |
| 3DTopia-XL | `ghcr.io/hitsuki-ban/3dgen-3dtopia-xl-runtime:2026-07-cloud-wave2-batch-a` | `sha256:f9a80c8d826bd1400e02676e066b28d65f45a29eec518788ab00fac1a9e140dd` | Uses `rembg[cpu]`, `numpy==1.26.4`, and source-built PyTorch3D v0.7.9. |
| Direct3D-S2 | `ghcr.io/hitsuki-ban/3dgen-direct3d-s2-runtime:2026-07-cloud-wave2-batch-b-v4` | index `sha256:b039ea24105baaef1ab09b551452164bd34acf7bb5b658c32c1ae488dd91cff9`; linux/amd64 `sha256:5c9aadd6d180208cdc437a65b430810e886364d4244e591e67b8b47a457c70e2` | CUDA 12.8 / torch 2.7.1, source-built `torchsparse`, `flash-attn==2.8.3`, and Direct3D-S2 voxelize `udf_ext`; runner records upstream `LICENSE.txt`. |
| Step1X-3D | `ghcr.io/hitsuki-ban/3dgen-step1x-3d-runtime:2026-07-cloud-wave2-batch-b-v1` | index `sha256:98136326d753401b0092130fc484ae30249b52b833c4dac00106ca43335f131c`; linux/amd64 `sha256:b3b3420343459cb1391c128b71c66eb035bc20a1f4135f8821bd1fb80d138b3e` | CUDA 12.8 / torch 2.7.1 runtime-only image. Step1X requirements need `--no-build-isolation` because upstream `pytorch3d@stable` imports the already-installed torch during build. |

## Published Site Data

| Model | Run prefix | Site-data prefix | Success | Failure | Site objects | Avg seconds | Max VRAM |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `trellis1` | `runs/trellis1/wave2/20260709T013634Z/` | `site-data/trellis1/` | 25 | 0 | 75 | `47.011` | `19.588 GiB` |
| `3dtopia-xl` | `runs/3dtopia-xl/wave2/20260709T050629Z/` | `site-data/3dtopia-xl/` | 25 | 0 | 75 | `76.362` | `10.016 GiB` |
| `direct3d-s2` | `runs/direct3d-s2/wave2/20260709T103859Z/` | `site-data/direct3d-s2/` | 25 | 0 | 75 | `140.106` | `30.590 GiB` |

Trellis v1 task metadata spans `2026-07-09T01:39:44Z` through `2026-07-09T02:03:48Z`.
3DTopia-XL task metadata spans `2026-07-09T05:12:14Z` through `2026-07-09T05:54:51Z`.
Direct3D-S2 task metadata spans `2026-07-09T10:43:05Z` through `2026-07-09T11:56:53Z`.
The final successful 3DTopia-XL run moved the balance by about `$0.5625982428`.
Latest REST billing visible after the Direct3D-S2 publish included `$1.0415233377` across the Direct3D-S2 staging/smoke/full pods, but the full-run pod's final billing appeared partially delayed at check time. Runtime estimate for the full pod is about `$1.4` at `$0.99/hr`.

Both published prefixes were rechecked after upload:

- `site-data/trellis1/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="trellis1"`.
- `site-data/3dtopia-xl/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="3dtopia-xl"`.
- `site-data/direct3d-s2/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="direct3d-s2"` and `gpu_name="NVIDIA GeForce RTX 5090"`.

## Debug Notes

- TRELLIS v1 first failed on all tasks with subprocess `SIGFPE` while the upstream default used `SPCONV_ALGO=auto`. Setting `SPCONV_ALGO=native` in the runtime image and runner fixed the cloud run.
- 3DTopia-XL required three runtime fixes before the successful image:
  - `rembg[cpu]` so `onnxruntime` is present for background removal.
  - `numpy==1.26.4` because PyTorch 2.1.2 fails against NumPy 2.x at runtime.
  - PyTorch3D v0.7.9 built from source because no matching official wheel was available for Python 3.9 / CUDA 11.8 / torch 2.1.2.
- Docker Desktop BuildKit returned an EOF once during the PyTorch3D build. Restarting Docker Desktop and rebuilding with `MAX_JOBS=1` for PyTorch3D completed the image.
- As with wave 1, the final `runpod-status.json` was not present after self-termination, but per-task incremental uploads preserved the full task result set.
- Direct3D-S2 image v2 reached staging but its first cloud smoke failed because upstream imports require the compiled voxelize extension `udf_ext`.
- Direct3D-S2 image v3 added `flash-attn`, `udf_ext`, `accelerate`, `kornia`, and `prettytable`. The RTX 4090 smoke then failed with CUDA OOM near 23 GiB in the refiner path, matching the issue's 5090 Batch B placement. The RTX 5090 smoke got through inference but failed packaging because the runner required `/opt/Direct3D-S2/LICENSE`; the pinned upstream repo actually ships `LICENSE.txt`.
- Direct3D-S2 image v4 fixed the license source path. The 2-task RTX 5090 smoke succeeded with mean `166.176s` and max VRAM `27.559 GiB`.
- The full Direct3D-S2 pod uploaded all 25 task outputs but did not self-terminate after the object count stabilized at 175. It was manually deleted via REST `DELETE /pods/mce6en0xdr1g08`; `bench-harness runpod-pods` then returned `[]`.
- Step1X-3D image v1 built and pushed after splitting the requirements install from the torch install and running upstream requirements with `MAX_JOBS=1 uv pip install --system --no-build-isolation`.
- Step1X-3D first 2-task RTX 5090 smoke at `runs/step1x-3d/wave2-smoke/20260709T133043Z/` failed before inference because upstream geometry loads `facebook/dinov2-with-registers-large` by repo id while runtime is offline.
- The first DINOv2 staging attempt wrote to the wrong cache shape for runtime lookup. The successful CPU staging report `runs/staging/20260709T135531Z/network-volume-wnqijpazd5-step1x-dinov2-cache-v3-cpu.json` cached the default `main` ref under `/workspace/hf/hub`; offline `AutoConfig`, `AutoImageProcessor`, and `AutoModel` then loaded `Dinov2WithRegistersModel`.
- Step1X-3D second 2-task RTX 5090 smoke at `runs/step1x-3d/wave2-smoke/20260709T140039Z/` completed the 50-step geometry phase and generated mesh, then failed in texture setup because `madebyollin/sdxl-vae-fp16-fix` was not yet cached.
- Texture dependencies were staged by CPU pod in `runs/staging/20260709T141027Z/network-volume-wnqijpazd5-step1x-texture-deps-v1-cpu.json`: `stabilityai/stable-diffusion-xl-base-1.0` minimal runtime subset (`13.544 GiB`), `madebyollin/sdxl-vae-fp16-fix` (`0.335 GiB`), and `ZhengPeng7/BiRefNet` (`0.445 GiB`). Offline config/tokenizer checks and BiRefNet load passed.
- After the texture dependency staging, EU-RO-1 briefly returned `There are no instances currently available` for RTX 5090 and A100 80GB fallback GPU types.
- A later fallback smoke at `runs/step1x-3d/wave2-smoke/20260709T142814Z/` landed on a `$1.39/hr` high-VRAM instance. It confirmed that SDXL, VAE, and BiRefNet load from offline cache, but both tasks failed in the texture renderer with `nvdiffrast` `Cuda error: 209[cudaFuncGetAttributes(&attr, (void*)fineRasterKernel);]`. This matches a compiled CUDA-architecture mismatch for the A100 fallback path; Step1X v1 was built for RTX 4090/5090 architectures (`8.9;12.0`).
- The A100 fallback is not being promoted for a full Step1X run: the first failed task took about 7 minutes before the renderer failure, and `$1.39/hr` would push a 25-task run beyond the issue's `$3/model` guardrail. The next Step1X cloud action should retry RTX 5090 only.

## Remaining

- Batch B:
  - `trellis2`: runner/spec/Dockerfile added. Actual staging requires `HF_TOKEN` plus accepted access for `facebook/dinov3-vitl16-pretrain-lvd1689m` and `briaai/RMBG-2.0`; current local env does not provide `HF_TOKEN`.
  - `direct3d-s2`: complete and published.
  - `step1x-3d`: runner/spec/Dockerfile added after checking upstream `stepfun-ai/Step1X-3D` at commit `cb5ac944709c6c913109070c7b90c3447f57f3d4` and HF weights revision `bf7084495b3a72222f36549b7942948aa4d9daa7`. The benchmark path is official base geometry `Step1X-3D-Geometry-1300m` plus `Step1X-3D-Texture`; label geometry is not used. Main weights and external HF cache dependencies are staged; the next action is a new 2-task RTX 5090-only smoke when EU-RO-1 5090 capacity returns.
  - `pixal3d`: runner/spec/Dockerfile added after checking upstream `TencentARC/Pixal3D` at commit `cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af` and HF weights revision `0b31f9160aa400719af409098bff7936a932f726`. The benchmark path forces the official standard `1536_cascade`; it does not switch to low-VRAM `1024` on OOM.
- Batch C:
  - `hunyuan3d-21`: runner/spec/Dockerfile added after checking upstream `tencent-hunyuan/hunyuan3d-2.1` at commit `82920d643c0dc2f7bfd7255f45f62d386edfe60c` and HF weights revision `0b94677654c57bb9a6b6845cd7b704ccf551d327`. The spec records the EU27/GB/KR distribution block and preferred non-EU RunPod DC `US-KS-2`; actual execution still needs a dedicated non-EU network volume.
- Conditional:
  - `sf3d`, blocked until the owner provides a gated Hugging Face token with the Stability license accepted.

Current local secret state checked before this draft:

- `F:\WorkSpace\3DGSDemoRoom\.env` has `RUNPOD_API_KEY`.
- R2 S3 variables are present and were used for Direct3D-S2 publish.
- `HF_TOKEN` is not present in the file or current process environment.

## Source Checks

- TRELLIS: https://github.com/microsoft/TRELLIS
- 3DTopia-XL: https://github.com/3DTopia/3DTopia-XL
- Direct3D-S2: https://github.com/DreamTechAI/Direct3D-S2
- PyTorch3D v0.7.9 source tag: https://github.com/facebookresearch/pytorch3d/releases/tag/v0.7.9
- Step1X-3D: https://github.com/stepfun-ai/Step1X-3D
- Pixal3D: https://github.com/TencentARC/Pixal3D
- Hunyuan3D-2.1: https://github.com/tencent-hunyuan/hunyuan3d-2.1

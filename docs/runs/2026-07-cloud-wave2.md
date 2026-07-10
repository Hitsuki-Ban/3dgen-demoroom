# 2026-07 Cloud Wave 2

Checked: 2026-07-10 JST
Issue: #37

## Status

Batch A, `direct3d-s2`, `sf3d`, and `trellis2` have completed and have been published to the public site-data prefixes in R2.
The remaining Batch B/C models stay in scope for the same issue/PR.

- Active RunPod pods after Pixal3D publish and temporary-volume cleanup: `[]`.
- Final RunPod balance for this report: `$5.5579990944`.
- RunPod GraphQL balance and runtime telemetry work with the explicit harness User-Agent; REST Pods and Billing remain the authoritative lifecycle and cost endpoints.
- RunPod reported the EU-RO-1 RTX 4090 runtime price as `$0.69/hr` during the paid runs, higher than the `$0.34/hr` value captured in the issue text.
- RunPod reported the EU-RO-1 RTX 5090 runtime price as `$0.99/hr` during `direct3d-s2` staging, smoke, and full runs.
- EU-RO-1 network volume `wnqijpazd5` was expanded from 30GB to 80GB and then to 120GB for wave 2 staging.
- Hunyuan3D-2.1 dedicated non-EU network volume `dzy02pljaw` was created in `US-KS-2` with size 40GB, then deleted with HTTP 204 after the DC lost target GPU capacity and the remaining budget could no longer fund execution.
- Stable Fast 3D staging reports:
  - `runs/staging/20260710T035828Z/network-volume-wnqijpazd5-sf3d-v1.json` staged the gated SF3D snapshot and public DINOv2 Large cache.
  - `runs/staging/20260710T040724Z/network-volume-wnqijpazd5-sf3d-openclip-v1.json` staged the OpenCLIP dependency found by the first smoke.
- TRELLIS.2 staging reports:
  - `runs/staging/20260710T050112Z/network-volume-wnqijpazd5-trellis2-v1.json` failed validation because the generated HF `refs/main` files contained trailing newlines.
  - `runs/staging/20260710T050307Z/network-volume-wnqijpazd5-trellis2-v2.json` staged and validated the 14.820GB main snapshot plus pinned DINOv3, RMBG-2.0, and TRELLIS-image-large cache entries with exact newline-free refs.
- Pixal3D staging reports:
  - `runs/staging/20260710T092342Z/network-volume-wnqijpazd5-disk-audit-v1.json` found 73.192GB of stale Xet temporary data under `weights/Pixal3D/.cache`, which had filled the 120GB volume and surfaced as the generic `Background writer channel closed` error.
  - `runs/staging/20260710T092538Z/network-volume-wnqijpazd5-pixal3d-main-v5-cpu-clean-sequential.json` removed that exact disposable cache and validated all 16 main files (`24,044,873,669` bytes).
  - `runs/staging/20260710T092850Z/network-volume-wnqijpazd5-pixal3d-external-v1-cpu.json` staged DINOv3, MoGe-2, RMBG-2.0, and the pinned NAF source/checkpoint (`3,405,262,748` bytes).
  - `runs/staging/20260710T094028Z/network-volume-wnqijpazd5-trellis2-pixal3d-validate-v1.json` jointly validated 22 required files, five exact HF refs, the NAF commit marker, and checkpoint SHA-256.
  - `runs/staging/20260710T110413Z/pixal3d-us-48gb-v1.json` staged the same pinned assets on temporary 80GB US-WA-1 volume `i778cihpqd`: `24,044,888,779` main bytes and `15,451,314,021` external/cache bytes. The RTX 6000 Ada staging pod ran at `$0.77/hr` for about 3.4 minutes and self-deleted; the volume was deleted with HTTP 204 after publish validation.
- Wave 2 staging validation report: `runs/staging/20260709T005450Z/network-volume-wnqijpazd5-wave2-batch-a-validate.json`
- Direct3D-S2 staging validation report: `runs/staging/20260709T090135Z/network-volume-wnqijpazd5-direct3d-s2-v2-fast.json`
- Step1X-3D main weights staging report: `runs/staging/20260709T131830Z/network-volume-wnqijpazd5-step1x-3d-v1.json`
- Step1X-3D external HF cache reports:
  - `runs/staging/20260709T135531Z/network-volume-wnqijpazd5-step1x-dinov2-cache-v3-cpu.json`
  - `runs/staging/20260709T141027Z/network-volume-wnqijpazd5-step1x-texture-deps-v1-cpu.json`
- Hunyuan3D-2.1 non-EU staging reports:
  - `runs/staging/20260709T145905Z/network-volume-dzy02pljaw-hunyuan3d-21-us-ks-2-v1.json` downloaded the assets but failed its optional `AutoImageProcessor` import check because the slim staging image did not include PyTorch/torchvision.
  - `runs/staging/20260709T150120Z/network-volume-dzy02pljaw-hunyuan3d-21-us-ks-2-verify-v1.json` verified the mounted file set and DINOv2 `refs/main`.
- Latest capacity-only launch attempts that did not create pods:
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T161427Z/`, `US-KS-2`, GPU priority `NVIDIA L40S` / `NVIDIA L40` / `NVIDIA RTX 6000 Ada Generation`, REST response `There are no instances currently available`.
  - `step1x-3d`: `runs/step1x-3d/wave2-smoke/20260709T161510Z/`, `EU-RO-1`, RTX 5090-only, REST response `There are no instances currently available`.
- Follow-up capacity and A100 fallback attempts:
  - `step1x-3d`: `runs/step1x-3d/wave2-smoke/20260709T162318Z/`, `EU-RO-1`, RTX 5090-only, REST response `There are no instances currently available`.
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T162341Z/`, `US-KS-2`, GPU priority `NVIDIA L40S` / `NVIDIA L40` / `NVIDIA RTX 6000 Ada Generation`, REST response `There are no instances currently available`.
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T164646Z/`, `US-KS-2`, A100 priority `NVIDIA A100 80GB PCIe` / `NVIDIA A100-SXM4-80GB`, created pod `zpwqutkz3k41dr` on `NVIDIA A100-SXM4-80GB` at `$1.49/hr`. The pod briefly exposed `publicIp` and SSH port, then lost `publicIp`; R2 stayed empty after about 15 minutes, so it was manually deleted. `GET /v1/billing/pods?podId=zpwqutkz3k41dr` returned `[]` at the immediate post-cleanup check, so billing had not backfilled yet.
- Post-v8 capacity attempts:
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T172306Z/`, `US-KS-2`, GPU priority `NVIDIA L40S` / `NVIDIA L40` / `NVIDIA RTX 6000 Ada Generation`, REST response `There are no instances currently available`.
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T172329Z/`, `US-KS-2`, A100 priority `NVIDIA A100 80GB PCIe` / `NVIDIA A100-SXM4-80GB`, REST response `There are no instances currently available`.
  - `step1x-3d`: `runs/step1x-3d/wave2-smoke/20260709T172350Z/`, `EU-RO-1`, RTX 5090-only, REST response `There are no instances currently available`.
  - `step1x-3d`: `runs/step1x-3d/wave2-smoke/20260709T173108Z/`, `EU-RO-1`, RTX 5090-only, REST response `There are no instances currently available`.
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T173108Z-ada/`, `US-KS-2`, GPU priority `NVIDIA L40S` / `NVIDIA L40` / `NVIDIA RTX 6000 Ada Generation`, REST response `There are no instances currently available`.
  - `hunyuan3d-21`: `runs/hunyuan3d-21/wave2-smoke/20260709T173108Z-a100/`, `US-KS-2`, A100 priority `NVIDIA A100 80GB PCIe` / `NVIDIA A100-SXM4-80GB`, REST response `There are no instances currently available`.
- Step1X follow-up after capacity returned:
  - `runs/step1x-3d/wave2-smoke/20260710T044345Z/` created RTX 5090 pod `5u1ot3wdgtbemr` at `$0.99/hr`. Geometry completed, but the first task failed in the official texture path while VAE encoding requested another `3.94 GiB`; the 31.37 GiB GPU already had 29.93 GiB in use. The pod was manually deleted before repeating the deterministic OOM on task two.
  - One-task fallback creates for EU-RO-1 `NVIDIA RTX PRO 6000 Blackwell Workstation Edition` (`$1.89/hr`) and Server Edition (`$1.99/hr`) both returned `There are no instances currently available`; no pod was created.
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
| Hunyuan3D-2.1 | `ghcr.io/hitsuki-ban/3dgen-hunyuan3d-21-runtime:2026-07-cloud-wave2-batch-c-v8` | index `sha256:38519b32e32495cdbe29bd8d99e2554f10f836041f3eba951d16d7b22e5005cf`; linux/amd64 `sha256:7541ce5555e5c3d5b5f10f5e4f76af6691c54f02b26bdf7b583afef5c0b69720` | CUDA 12.4 / torch 2.5.1+cu124 runtime-only image, compiled for A100 `sm_80` and Ada `sm_89`; explicitly installs `boto3` for R2 uploads. Actual execution is waiting for US-KS-2 GPU capacity. |
| Stable Fast 3D | `ghcr.io/hitsuki-ban/3dgen-sf3d-runtime:2026-07-cloud-wave2-v2` | index `sha256:85216246b71697fc81288fc13d887d7738fa1ab5835192122e46b96be5a6dbb8`; linux/amd64 `sha256:9554af7dd8bdf3f07991a63e0237e3fff30ac10696545630fd8822d7a59aa08d` | CUDA 12.8 / torch 2.7.1 runtime-only image. Uses staged SF3D, DINOv2 Large, OpenCLIP, and U2NET assets with Hub offline mode enabled. |
| TRELLIS.2 | `ghcr.io/hitsuki-ban/3dgen-trellis2-runtime:2026-07-cloud-wave2-v6` | index `sha256:2353fe6ec49e440dd7fb7ef4197a491632b3afe537c0c1de5f588b89b056ad54`; linux/amd64 `sha256:f19b40ed4000e82c722cfe120ac0805f93e5108b8a2692bd4bfa088307027555` | CUDA 12.8 / torch 2.7.1, pinned Transformers 4.57.3 and FlashAttention 2.8.3. Adds exact task selection, staged external-cache validation, and task-prefix replacement uploads for auditable retries. |
| Pixal3D | `ghcr.io/hitsuki-ban/3dgen-pixal3d-runtime:2026-07-cloud-wave2-v2` | index `sha256:2d2af8534def632e03f19f62673afbba5ca290359f98f270a01216db4959bc33`; linux/amd64 `sha256:4c1d1c76a865b81e62579a05b4f10ded25f279c857d07e8e0df624885cb299b4` | Installs a verified NATTEN 0.21.0 wheel from private builder manifest `sha256:bcbadc4205c6c80282d8360a3eeb4eeeae0f9d6c4b5f17f91cccff7281bdafb4`; wheel SHA-256 `a0bccfb8da194fc909eddaf77573b6a12303839a4bc70964240a7b10546631c0`. |

## Published Site Data

| Model | Run prefix | Site-data prefix | Success | Failure | Site objects | Avg seconds | Max VRAM |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `trellis1` | `runs/trellis1/wave2/20260709T013634Z/` | `site-data/trellis1/` | 25 | 0 | 75 | `47.011` | `19.588 GiB` |
| `3dtopia-xl` | `runs/3dtopia-xl/wave2/20260709T050629Z/` | `site-data/3dtopia-xl/` | 25 | 0 | 75 | `76.362` | `10.016 GiB` |
| `direct3d-s2` | `runs/direct3d-s2/wave2/20260709T103859Z/` | `site-data/direct3d-s2/` | 25 | 0 | 75 | `140.106` | `30.590 GiB` |
| `sf3d` | `runs/sf3d/wave2/20260710T042618Z/` | `site-data/sf3d/` | 25 | 0 | 75 | `11.609` | `7.668 GiB` |
| `trellis2` | `runs/trellis2/wave2/20260710T080630Z/` | `site-data/trellis2/` | 25 | 0 | 75 | `280.977` | `33.148 GiB` |
| `pixal3d` | `runs/pixal3d/wave2/20260710T113319Z/` | `site-data/pixal3d/` | 23 | 2 | 71 | `331.811` | `45.900 GiB` |

Trellis v1 task metadata spans `2026-07-09T01:39:44Z` through `2026-07-09T02:03:48Z`.
3DTopia-XL task metadata spans `2026-07-09T05:12:14Z` through `2026-07-09T05:54:51Z`.
Direct3D-S2 task metadata spans `2026-07-09T10:43:05Z` through `2026-07-09T11:56:53Z`.
Stable Fast 3D task metadata spans `2026-07-10T04:29:37Z` through `2026-07-10T04:37:15Z`.
TRELLIS.2 task metadata spans `2026-07-10T08:09:37Z` through the 96GB exact retry at `2026-07-10T10:31:31Z`.
Pixal3D successful task metadata spans `2026-07-10T11:42:03Z` through `2026-07-10T14:02:55Z`; its 23 top-level GLBs total `931,217,000` bytes.
The final successful 3DTopia-XL run moved the balance by about `$0.5625982428`.
Latest REST billing visible after the Direct3D-S2 publish included `$1.0415233377` across the Direct3D-S2 staging/smoke/full pods, but the full-run pod's final billing appeared partially delayed at check time. Runtime estimate for the full pod is about `$1.4` at `$0.99/hr`.
Stable Fast 3D moved the GraphQL balance from `$12.3439651237` to `$12.1234134208`, or about `$0.220552` total for two CPU staging pods, one dependency-failure smoke, one successful smoke, and the 25-task full run. Per-pod REST billing had not backfilled at the final check.
Final REST billing for the TRELLIS.2 5090 full and 96GB exact-retry pods is `$2.124035` and `$0.520187`. Pixal3D US-WA-1 staging, 48GB smoke, and full pods cost `$0.047023`, `$0.285622`, and `$1.250501`; the earlier 5090 OOM smoke cost `$0.172966`.

Both published prefixes were rechecked after upload:

- `site-data/trellis1/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="trellis1"`.
- `site-data/3dtopia-xl/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="3dtopia-xl"`.
- `site-data/direct3d-s2/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="direct3d-s2"` and `gpu_name="NVIDIA GeForce RTX 5090"`.
- `site-data/sf3d/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="sf3d"`.
- `site-data/trellis2/`: 75 objects, 25 task directories, no `failure.json`; the exact-retry sample records `gpu_name="NVIDIA RTX PRO 6000 Blackwell Workstation Edition"`.
- `site-data/pixal3d/`: 71 objects, 25 task directories, 23 `meta.json`/GLB results and two `failure.json` records for the CuMesh postprocess OOM tasks.

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
- Pixal3D dependency check found that pinned `TencentARC/Pixal3D` `pipeline.json` uses `briaai/RMBG-2.0` for background removal. `camenduru/dinov3-vitl16-pretrain-lvd1689m` and `Ruicheng/moge-2-vitl` are public, but unauthenticated `hf_hub_download` for `briaai/RMBG-2.0/config.json` returns `GatedRepoError 401`. The spec now records `briaai/RMBG-2.0` as the actual gated dependency for the standard path and does not include unused `black-forest-labs/FLUX.1-dev`.
- Hunyuan3D-2.1 staging used non-EU `US-KS-2` volume `dzy02pljaw` to comply with the license location constraint. Verified staged bytes: Hunyuan repo `14.977 GiB`, DINOv2 giant cache `4.546 GiB`, plus `RealESRGAN_x4plus.pth` `67.041 MB`. Fable's Hunyuan geo-block PR #38 is merged, so public serving guardrails are in place once data is published.
- Hunyuan3D-2.1 runtime build needed four build-path fixes before v6:
  - Upstream requirements had to be installed with torch/xformers constraints and `--no-build-isolation`; otherwise isolated sdist builds pulled CUDA 13 torch dependencies instead of the intended torch 2.5.1/cu124 environment.
  - Upstream `requirements.txt` pins `bpy==4.0`, which is no longer resolved by the default PyPI/mirror index path. The Dockerfile rewrites it to Blender's official archived `bpy-4.0.0-cp310-cp310-manylinux_2_28_x86_64.whl` URL and checks that the rewrite happened.
  - `compile_mesh_painter.sh` called `python -m pybind11 --includes`, but the Ubuntu base only has `python3`. The Dockerfile rewrites that command to `python3 -m pybind11 --includes`, which also supplies the missing `pybind11/numpy.h` include.
  - Local Docker Desktop build cache and image layers were pruned after failed attempts and after the successful push; `docker system df` returned 0 images / 0 build cache before the latest cloud launch attempts.
- Hunyuan3D-2.1 runtime v7 changed `TORCH_CUDA_ARCH_LIST` from `8.9` to `8.0;8.9` so the issue-approved A100 fallback can use the same runtime path as the Ada candidates. The v7 build was pushed, then local Docker image and BuildKit cache were pruned back to `0B`.
- The v7 A100 no-telemetry smoke exposed two telemetry gaps: the Hunyuan Dockerfile did not explicitly install `boto3`, while both final and incremental R2 upload paths depend on `bench_harness.uploader`; and `build_cloud_run_command` only wrote `runpod-status.json` after the model runner returned. Runtime image v8 adds explicit `boto3`, and the launcher command now writes and uploads `runpod-startup.json` before entering the runner. If startup status writing or uploading fails, the command skips the runner and exits through the final status/termination path.
- Hunyuan3D-2.1 2-task smoke launch attempts after the v6 image did not create pods:
  - Initial post-v6 attempt: `US-KS-2`, RTX 6000 Ada only, REST response `There are no instances currently available`.
  - `20260709T161427Z`: `US-KS-2`, L40S / L40 / RTX 6000 Ada priority, REST response `There are no instances currently available` for all three GPU types.
- Hunyuan3D-2.1 v7 A100 fallback smoke at `runs/hunyuan3d-21/wave2-smoke/20260709T164646Z/` created pod `zpwqutkz3k41dr` on `US-KS-2` `NVIDIA A100-SXM4-80GB`, but no task output or `runpod-status.json` reached R2 before the pod lost `publicIp`. The smoke was manually deleted at about 15 minutes to stay within the budget guardrail. RunPod REST returned 400 for guessed pod log paths such as `/v1/pods/zpwqutkz3k41dr/logs`, so no container logs were available through the current API path.
- Hunyuan v8 could not be smoke-tested after build because repeated US-KS-2 48GB Ada and A100 priorities returned capacity misses before pod creation, most recently at `20260709T173108Z`.
- Stable Fast 3D is pinned to code commit `ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2` and weights revision `f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778`. Its first smoke at `runs/sf3d/wave2-smoke/20260710T040101Z/` found the official config's implicit OpenCLIP dependency; both tasks failed before inference and the pod was deleted. After staging `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` revision `1a25a446712ba5ee05982a381eed697ef9b435cf`, the v2 smoke at `runs/sf3d/wave2-smoke/20260710T042004Z/` completed 2/2 tasks. The first task took `58.945s` including cold model/cache load, and the second took `9.390s`.
- Step1X RTX 5090 no longer qualifies as a full-run path for the official defaults on the current runtime: the runner already moves the geometry pipeline to CPU, deletes it, and empties the CUDA cache before loading texture, yet the texture VAE still OOMs above 32GB. The existing A100 image is not compiled for `sm_80`, and the previous A100 timing projected above the `$3/model` guardrail. The next valid retry is the existing `sm_120` image on a 96GB RTX PRO 6000 Blackwell when EU-RO-1 capacity returns.
- The later two-task Step1X confirmation at `runs/step1x-3d/wave2-smoke/20260710T104748Z/` recorded 2/2 official texture-path OOM failures on RTX 5090 after geometry succeeded. This confirms the blocker is capacity rather than the previously missing SDXL/VAE/BiRefNet caches or A100-only `nvdiffrast` architecture mismatch.
- TRELLIS.2 image v3 failed its first smoke because unpinned Transformers 5.13 changed the DINOv3 model API expected by the pinned upstream code. Image v4 pinned Transformers 4.57.3 but its xFormers attention path failed on RTX 5090. Image v5 changed dense and sparse attention to FlashAttention 2.8.3; `runs/trellis2/wave2-smoke/20260710T074935Z/` then completed 2/2 tasks.
- TRELLIS.2 v5 smoke task times were `313.308s` and `205.079s`, with peak VRAM of `10.677 GiB` and `8.218 GiB`. The full run uses the same official 1024 cascade, 4096 texture, and postprocess defaults.
- TRELLIS.2 full run produced 24 successes and one deterministic CuMesh `fill_holes` OOM on the 32GB RTX 5090. Exact task retry prefix `runs/trellis2/wave2-retry/20260710T101807Z/` reran only `fluffy-monster-plush` on a 96GB RTX PRO 6000 Blackwell Workstation, succeeded in `587.905s`, and replaced the canonical task prefix before publish. Final canonical results are 25/25 success; the 5090 full pod's currently visible REST billing is `$1.553942`, with retry billing still delayed.
- Hugging Face Xet can collapse underlying volume I/O errors into `Internal Writer Error: Background writer channel closed`. The Pixal3D disk audit showed that repeated interrupted `local_dir` downloads had retained 73.192GB in `.cache` while only 2.048GB of final files existed. Removing only that reproducible cache made the next sequential Xet download complete in `76.586s`.
- Pixal3D uses the official NATTEN 0.21.0 source build for both `sm_89` and `sm_120`. A four-worker local build on the 32GB workstation projected several hours and kept Docker's WSL VHD on C: large, so the wheel build moved to a 16-vCPU/128GB RunPod CPU pod and records the official sdist SHA-256 in R2.
- Pixal3D standard 1536 smoke `runs/pixal3d/wave2-smoke/20260710T103501Z/` recorded 2/2 CUDA OOM failures on RTX 5090; the first needed another 6.75GiB with only 5.19GiB free. No low-VRAM 1024 path was used. After US-WA-1 restaging, `runs/pixal3d/wave2-smoke/20260710T110858Z-us-wa-1-48gb/` completed 2/2 on RTX 6000 Ada in `571.842s` and `472.670s`, with peak VRAM about `41.35GiB`. The measured 25-task projection is `3.627h / $2.793` at `$0.77/hr`, below the issue's `$3/model` guardrail.
- Pixal3D full run completed 23/25 on RTX 6000 Ada. `ornate-treasure-chest` and `old-oak-tree` both reached CuMesh simplify after inference but OOMed in postprocess. A combined 96GB exact-task retry at US-WA-1 returned no capacity before pod creation, so the two protocol failures were published rather than changing resolution or postprocess defaults.
- Docker Desktop's internal store was pruned to zero, its empty 112.7GiB C: VHD was recreated, and Docker Desktop's supported disk-image-location setting moved the new data root to `F:\WorkSpace\3DGSDemoRoom\.docker-data\DockerDesktopWSL`. External buildx caches remain under `.docker-build`; both directories are ignored by Git.
- The shared cloud command invokes `python3 -m bench_harness.cli upload-s3` for startup and final telemetry. `bench_harness.cli` previously lacked a module entrypoint, so those invocations were no-ops even though per-task direct uploads worked. The CLI now calls `main()` under `if __name__ == "__main__"`, with a subprocess regression test. New runtime images built from this commit will upload `runpod-startup.json` and `runpod-status.json` as intended.

## Remaining

- Batch B:
  - `trellis2`: complete and published, 25 success / 0 failure after one exact-task 96GB retry.
  - `direct3d-s2`: complete and published.
  - `step1x-3d`: runner/spec/Dockerfile added after checking upstream `stepfun-ai/Step1X-3D` at commit `cb5ac944709c6c913109070c7b90c3447f57f3d4` and HF weights revision `bf7084495b3a72222f36549b7942948aa4d9daa7`. The benchmark path is official base geometry `Step1X-3D-Geometry-1300m` plus `Step1X-3D-Texture`; label geometry is not used. Main weights and external HF cache dependencies are staged. The RTX 5090 texture path OOMs above 32GB, so the next retry is a one-task 96GB RTX PRO 6000 Blackwell smoke when EU-RO-1 capacity returns.
  - `pixal3d`: published with 23 success / 2 documented CuMesh OOM failures at the official standard `1536_cascade`; no low-VRAM fallback was used and the temporary US volume is deleted.
- Batch C:
  - `hunyuan3d-21`: runner/spec/Dockerfile added after checking upstream `tencent-hunyuan/hunyuan3d-2.1` at commit `82920d643c0dc2f7bfd7255f45f62d386edfe60c` and HF weights revision `0b94677654c57bb9a6b6845cd7b704ccf551d327`. Runtime image v8 is built for `sm_80;sm_89` with explicit R2 upload dependencies. The historical US-KS-2 staging reports remain in R2, but volume `dzy02pljaw` was deleted after that DC lost target GPU capacity; a future funded retry must stage into a supported non-EU DC with live 48GB/A100 inventory.
- Conditional:
  - `sf3d`: complete and published.

The remaining balance margin above the `$4` stop line is `$1.558`. That is insufficient for either the measured Step1X high-memory full path or Hunyuan3D-2.1 staging plus full execution, so neither model receives another paid launch in this report.

Current local secret state checked before this draft:

- `F:\WorkSpace\3DGSDemoRoom\.env` has `RUNPOD_API_KEY`.
- R2 S3 variables are present and were used for Direct3D-S2 publish.
- `HF_TOKEN` is present and was verified against the gated dependencies required by `sf3d`, `pixal3d`, and `trellis2`.

## Source Checks

- TRELLIS: https://github.com/microsoft/TRELLIS
- 3DTopia-XL: https://github.com/3DTopia/3DTopia-XL
- Direct3D-S2: https://github.com/DreamTechAI/Direct3D-S2
- PyTorch3D v0.7.9 source tag: https://github.com/facebookresearch/pytorch3d/releases/tag/v0.7.9
- Step1X-3D: https://github.com/stepfun-ai/Step1X-3D
- Pixal3D: https://github.com/TencentARC/Pixal3D
- Hunyuan3D-2.1: https://github.com/tencent-hunyuan/hunyuan3d-2.1
- Stable Fast 3D: https://github.com/Stability-AI/stable-fast-3d and https://huggingface.co/stabilityai/stable-fast-3d
- Blender `bpy` archived wheels: https://download.blender.org/pypi/bpy/

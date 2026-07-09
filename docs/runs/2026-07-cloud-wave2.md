# 2026-07 Cloud Wave 2

Checked: 2026-07-09
Issue: #37

## Status

Batch A has completed and has been published to the public site-data prefixes in R2.
The remaining Batch B/C models stay in scope for the same issue/PR.

- Active RunPod pods after Batch A: `[]`
- RunPod balance after the 3DTopia-XL publish check: `$16.2145592614`
- RunPod reported the EU-RO-1 RTX 4090 runtime price as `$0.69/hr` during the paid runs, higher than the `$0.34/hr` value captured in the issue text.
- EU-RO-1 network volume `wnqijpazd5` was expanded from 30GB to 80GB for wave 2 staging.
- Wave 2 staging validation report: `runs/staging/20260709T005450Z/network-volume-wnqijpazd5-wave2-batch-a-validate.json`
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

## Published Site Data

| Model | Run prefix | Site-data prefix | Success | Failure | Site objects | Avg seconds | Max VRAM |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `trellis1` | `runs/trellis1/wave2/20260709T013634Z/` | `site-data/trellis1/` | 25 | 0 | 75 | `47.011` | `19.588 GiB` |
| `3dtopia-xl` | `runs/3dtopia-xl/wave2/20260709T050629Z/` | `site-data/3dtopia-xl/` | 25 | 0 | 75 | `76.362` | `10.016 GiB` |

Trellis v1 task metadata spans `2026-07-09T01:39:44Z` through `2026-07-09T02:03:48Z`.
3DTopia-XL task metadata spans `2026-07-09T05:12:14Z` through `2026-07-09T05:54:51Z`.
The final successful 3DTopia-XL run moved the balance by about `$0.5625982428`.

Both published prefixes were rechecked after upload:

- `site-data/trellis1/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="trellis1"`.
- `site-data/3dtopia-xl/`: 75 objects, 25 task directories, sample `meta.json` has `model_id="3dtopia-xl"`.

## Debug Notes

- TRELLIS v1 first failed on all tasks with subprocess `SIGFPE` while the upstream default used `SPCONV_ALGO=auto`. Setting `SPCONV_ALGO=native` in the runtime image and runner fixed the cloud run.
- 3DTopia-XL required three runtime fixes before the successful image:
  - `rembg[cpu]` so `onnxruntime` is present for background removal.
  - `numpy==1.26.4` because PyTorch 2.1.2 fails against NumPy 2.x at runtime.
  - PyTorch3D v0.7.9 built from source because no matching official wheel was available for Python 3.9 / CUDA 11.8 / torch 2.1.2.
- Docker Desktop BuildKit returned an EOF once during the PyTorch3D build. Restarting Docker Desktop and rebuilding with `MAX_JOBS=1` for PyTorch3D completed the image.
- As with wave 1, the final `runpod-status.json` was not present after self-termination, but per-task incremental uploads preserved the full task result set.

## Remaining

- Batch B:
  - `trellis2`: runner/spec/Dockerfile added. Actual staging requires `HF_TOKEN` plus accepted access for `facebook/dinov3-vitl16-pretrain-lvd1689m` and `briaai/RMBG-2.0`; current local env does not provide `HF_TOKEN`.
  - `direct3d-s2`: runner/spec/Dockerfile added. Next step is image build + weight staging + 1-2 task smoke before the 25-task run.
  - `step1x-3d`
  - `pixal3d`
- Batch C:
  - `hunyuan3d-21` on a non-EU/non-UK/non-KR data center with a dedicated network volume.
- Conditional:
  - `sf3d`, blocked until the owner provides a gated Hugging Face token with the Stability license accepted.

Current local secret state checked before this draft:

- `F:\WorkSpace\3DGSDemoRoom\.env` has `RUNPOD_API_KEY`.
- R2 S3 variables are not present in the file or current process environment.
- `HF_TOKEN` is not present in the file or current process environment.

## Source Checks

- TRELLIS: https://github.com/microsoft/TRELLIS
- 3DTopia-XL: https://github.com/3DTopia/3DTopia-XL
- PyTorch3D v0.7.9 source tag: https://github.com/facebookresearch/pytorch3d/releases/tag/v0.7.9

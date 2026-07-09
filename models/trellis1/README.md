# TRELLIS v1 Runner

This runner implements the benchmark container contract for TRELLIS v1 image-to-3D.

## Build

```powershell
.\scripts\docker-build-model.ps1 trellis1
```

The Dockerfile pins:

- Code: `microsoft/TRELLIS` at `442aa1e1afb9014e80681d3bf604e8d728a86ee7`
- Weights: `microsoft/TRELLIS-image-large` at `25e0d31ffbebe4b5a97464dd851910efc3002d96`
- Base: `nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04`
- Torch: `2.4.0` cu121

The container is runtime-only with respect to model weights. The RunPod network volume must provide:

- `/workspace/weights/TRELLIS-image-large`
- `/workspace/weights/TRELLIS-image-large/README.md`
- `/workspace/torch` with the DINOv2 torch hub cache
- `/workspace/weights/rembg` with the U2NET rembg cache

The runner uses TRELLIS' official `TrellisImageTo3DPipeline` and `postprocessing_utils.to_glb` path. It records the sampler defaults from `microsoft/TRELLIS-image-large/pipeline.json`: 25 sparse-structure steps and 25 SLat steps, both with `cfg_strength=5.0`, `cfg_interval=[0.5, 1.0]`, and `rescale_t=3.0`.

`ATTN_BACKEND=xformers` is pinned in the image and metadata because it is the official supported non-flash attention path and avoids compiling flash-attn for the first RTX 4090 cloud pass. `SPCONV_ALGO=native` follows the official single-run recommendation and avoids `spconv` startup benchmarking during benchmark tasks.

Expected output per task:

- `output.glb`
- `meta.json`
- `LICENSES.txt`
- `raw/trellis1/output.glb`
- `raw/trellis1/output_gaussian.ply`

# TripoSG Runner

This runner implements the benchmark container contract for TripoSG.

## Build

```powershell
.\scripts\docker-build-model.ps1 triposg
```

The Dockerfile pins:

- Code: `VAST-AI-Research/TripoSG` at `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c`
- Weights: `VAST-AI/TripoSG` at `2c1c516d22d58db486a058d98d31bb6177344e06`
- Background removal weights: `briaai/RMBG-1.4` at `2ceba5a5efaec153162aedea169f76caf9b46cf8`
- Base: `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`
- Torch: `2.7.1` cu128

The runner uses TripoSG's official image preprocessing and pipeline, but it does not call the official CLI because that path downloads Hugging Face snapshots at runtime without an explicit revision. The container downloads pinned code during build. Pinned weights are staged separately on the RunPod network volume, and the runner fails fast unless these environment variables are set:

- `TRIPOSG_WEIGHTS_PATH`
- `RMBG_WEIGHTS_PATH`

The default parameters are the official TripoSG generation path: `num_inference_steps=50`, `num_tokens=2048`, `use_flash_decoder=true`, and `flash_octree_depth=9`. These values are passed explicitly so `meta.json` records the full generation configuration.

Timing and VRAM notes:

- `wall_clock_seconds` includes the runner's per-task subprocess startup, Python/torch import, model loading, and mesh export.
- `peak_vram_bytes` is sampled from `nvidia-smi memory.used`. On a shared local workstation it can include other GPU processes.

## Run Two-Task Smoke

Prepare an input directory that contains `tasks.json` and `references/`.

```powershell
New-Item -ItemType Directory -Force outputs\triposg-smoke | Out-Null
docker run --rm --gpus all `
  -e MAX_RUNTIME_MIN=60 `
  -e TRIPOSG_WEIGHTS_PATH=/workspace/weights/TripoSG `
  -e RMBG_WEIGHTS_PATH=/workspace/weights/RMBG-1.4 `
  -v ${PWD}\tasks:/work/input:ro `
  -v <local-or-network-weight-root>:/workspace/weights:ro `
  -v ${PWD}\outputs\triposg-smoke:/work/output `
  3dgen/triposg:local --task-limit 2
```

Expected output per task:

- `output.glb`
- `meta.json`
- `LICENSES.txt`
- `raw/triposg/output.glb`

Validate after the run:

```powershell
cd bench
uv run bench-harness output-validate ..\outputs\triposg-smoke\cartoon-apple
uv run bench-harness output-validate ..\outputs\triposg-smoke\crusty-bread-loaf
```

Local RTX 4070 Ti note: the official `flash_octree_depth=9` decoder path completed the diffusion loop but did not finish the first task's geometry extraction after more than 10 minutes on the 12GB local machine. A diagnostic run with `num_inference_steps=5`, `num_tokens=1024`, and `flash_octree_depth=8` completed in 46 seconds and exported a GLB, confirming the pinned image and runner path are viable. Full TripoSG generation should be scheduled for the cloud GPU phase rather than used as a local DoD gate.

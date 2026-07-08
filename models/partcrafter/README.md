# PartCrafter Runner

This runner implements the benchmark container contract for PartCrafter.

## Build

```powershell
.\scripts\docker-build-model.ps1 partcrafter
```

The Dockerfile pins:

- Code: `wgsxm/PartCrafter` at `3d773bf02fad51c7ab31a5615573fec93b287b30`
- Weights: `wgsxm/PartCrafter` at `69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f`
- Background removal weights: `briaai/RMBG-1.4` at `2ceba5a5efaec153162aedea169f76caf9b46cf8`
- Base: `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`
- Python: `3.11.13` managed by `uv`
- Torch: `2.7.0` cu128
- `torch-cluster`: PyG wheel index for `torch-2.7.0+cu128`

The runner uses PartCrafter's official pipeline, image preprocessing, and mesh-composition helper. It does not call the official CLI because that path downloads Hugging Face snapshots at runtime without an explicit revision and imports optional render/VLM code before argument handling. The runner keeps `part_suggest=false` and `style_transfer=false` so no external Gemini/API path is used.

The container downloads pinned code during build. Pinned weights are staged separately on the RunPod network volume, and the runner fails fast unless these environment variables are set:

- `PARTCRAFTER_WEIGHTS_PATH`
- `RMBG_WEIGHTS_PATH`

PartCrafter's official CLI substitutes a dummy triangle mesh when decoding returns `None`. This runner fails the task instead, because benchmark output should not silently contain placeholders.

Timing and VRAM notes:

- `wall_clock_seconds` includes the runner's per-task subprocess startup, Python/torch import, model loading, part generation, mesh composition, and export.
- `peak_vram_bytes` is sampled from `nvidia-smi memory.used`. On a shared local workstation it can include other GPU processes.

## Run Two-Task Smoke

Prepare an input directory that contains `tasks.json` and `references/`.

```powershell
New-Item -ItemType Directory -Force outputs\partcrafter-smoke | Out-Null
docker run --rm --gpus all `
  -e MAX_RUNTIME_MIN=60 `
  -e PARTCRAFTER_WEIGHTS_PATH=/workspace/weights/PartCrafter `
  -e RMBG_WEIGHTS_PATH=/workspace/weights/RMBG-1.4 `
  -v ${PWD}\tasks:/work/input:ro `
  -v <local-or-network-weight-root>:/workspace/weights:ro `
  -v ${PWD}\outputs\partcrafter-smoke:/work/output `
  3dgen/partcrafter:local --task-limit 2
```

Expected output per task:

- `output.glb`
- `meta.json`
- `LICENSES.txt`
- `raw/partcrafter/object.glb`
- `raw/partcrafter/part_00.glb` through `part_02.glb`
- `raw/partcrafter/manifest.json`

Validate after the run:

```powershell
cd bench
uv run bench-harness output-validate ..\outputs\partcrafter-smoke\cartoon-apple
uv run bench-harness output-validate ..\outputs\partcrafter-smoke\crusty-bread-loaf
```

# TripoSR Runner

This runner implements the benchmark container contract for TripoSR.

## Build

```powershell
.\scripts\docker-build-model.ps1 triposr
```

The Dockerfile pins:

- Code: `VAST-AI-Research/TripoSR` at `107cefdc244c39106fa830359024f6a2f1c78871`
- Weights: `stabilityai/TripoSR` at `5b521936b01fbe1890f6f9baed0254ab6351c04a`
- Base: `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`
- Torch: `2.7.1` cu128

The runner keeps TripoSR's official default preprocessing: rembg foreground extraction, foreground resizing with `--foreground-ratio 0.85`, and gray-background compositing. It intentionally does not pass `--no-remove-bg`.

The rembg U2NET model is downloaded during Docker build so the cold runtime path does not fetch that 176 MB asset.

TripoSR's official model config references `facebook/dino-vitb16` for the image tokenizer. The runner keeps that official lookup intact, so a cold container may fetch the small transformers config for that tokenizer on first run.

Timing and VRAM notes:

- `wall_clock_seconds` includes the runner's per-task subprocess startup, Python/torch import, and model loading time because this wrapper invokes official `run.py` once per task. It is consistent within TripoSR runs but should not be treated as a pure model-generation duration when comparing across different wrappers.
- New `peak_vram_bytes` results follow the explicit UUID/scope contract in [`bench/README.md`](../../bench/README.md): Linux host-PID process-group sampling or the RunPod-exclusive target-device mode. Historical TripoSR values are legacy shared-workstation device totals and are not process-scoped.

## Run Two-Task Smoke

Prepare an input directory that contains `tasks.json` and `references/`. The complete local contract run below requires a Linux/TCC host with host PID visibility; Windows WDDM can still validate the image and command path but cannot emit canonical per-process VRAM metadata.

```powershell
New-Item -ItemType Directory -Force outputs\triposr-smoke | Out-Null
docker run --rm --gpus all --pid=host `
  -e MAX_RUNTIME_MIN=60 `
  -e BENCH_VRAM_MEASUREMENT_MODE=process_group `
  -e BENCH_PID_NAMESPACE=host `
  -v ${PWD}\tasks:/work/input:ro `
  -v ${PWD}\outputs\triposr-smoke:/work/output `
  3dgen/triposr:local runner --task-limit 2
```

Expected output per task:

- `output.glb`
- `meta.json`
- `LICENSE`
- `raw/triposr/0/mesh.glb`

Validate after the run:

```powershell
cd bench
uv run bench-harness output-validate ..\outputs\triposr-smoke\cartoon-apple
uv run bench-harness output-validate ..\outputs\triposr-smoke\crusty-bread-loaf
```

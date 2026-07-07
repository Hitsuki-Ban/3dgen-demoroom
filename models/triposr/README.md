# TripoSR Runner

This runner implements the benchmark container contract for TripoSR.

## Build

```powershell
docker build -t 3dgen/triposr:local models/triposr
```

The Dockerfile pins:

- Code: `VAST-AI-Research/TripoSR` at `107cefdc244c39106fa830359024f6a2f1c78871`
- Weights: `stabilityai/TripoSR` at `5b521936b01fbe1890f6f9baed0254ab6351c04a`
- Base: `nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04`
- Torch: `2.7.1` cu128

TripoSR's official model config references `facebook/dino-vitb16` for the image tokenizer. The runner keeps that official lookup intact, so a cold container may fetch the small transformers config for that tokenizer on first run.

## Run Two-Task Smoke

Prepare an input directory that contains `tasks.json` and `references/`.

```powershell
New-Item -ItemType Directory -Force outputs\triposr-smoke | Out-Null
docker run --rm --gpus all `
  -e MAX_RUNTIME_MIN=60 `
  -v ${PWD}\tasks:/work/input:ro `
  -v ${PWD}\outputs\triposr-smoke:/work/output `
  3dgen/triposr:local --task-limit 2
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

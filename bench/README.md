# Bench Harness

This is the local-first benchmark harness for model runner outputs.

## Runner Contract

Container input:

- `/work/input/tasks.json`: JSON array of `{id, prompt, image, seed}`.
- `image` is relative to `/work/input`; the canonical repository layout uses `references/<task-id>.png`.

Container output per task:

- `/work/output/<task-id>/output.glb`
- `/work/output/<task-id>/meta.json`
- `/work/output/<task-id>/<license_file>` where `license_file` is declared by `meta.json`
- Any raw model output files required for audit/debugging

The canonical `meta.json` schema is enforced by `bench_harness.meta.REQUIRED_META_KEYS`.

## Local Commands

```powershell
cd bench
uv run pytest
uv run bench-harness tasks-validate ../tasks/tasks.json
uv run bench-harness output-validate <path-to-task-output-dir>
uv run bench-harness upload-local <source-dir> <target-root> runs/<model>/<gpu>/<timestamp>
```

## Cost Guardrails

- `MAX_RUNTIME_MIN` defaults to `60`, as specified in Issue #11. Non-positive values fail fast.
- When `RUNPOD_POD_ID` is present, RunPod self-termination requires `RUNPOD_API_KEY`; missing credentials fail fast.
- Remote RunPod launch is not implemented in this split PR. `bench_harness.runpod` only defines the balance-check request contract (`clientBalance`) for the next PR.
- S3/R2 upload is intentionally not implemented in this split PR. Selecting `s3` raises `NotImplementedError`; local upload is implemented.

## Source Pins Checked On 2026-07-08

Primary sources checked before this harness split:

| Model | Code source | Code commit | Weights source | Weights revision |
|---|---|---:|---|---:|
| TripoSR | `https://github.com/VAST-AI-Research/TripoSR` | `107cefdc244c39106fa830359024f6a2f1c78871` | `https://huggingface.co/stabilityai/TripoSR` | `5b521936b01fbe1890f6f9baed0254ab6351c04a` |
| TripoSG | `https://github.com/VAST-AI-Research/TripoSG` | `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c` | `https://huggingface.co/VAST-AI/TripoSG` | `2c1c516d22d58db486a058d98d31bb6177344e06` |
| PartCrafter | `https://github.com/wgsxm/PartCrafter` | `3d773bf02fad51c7ab31a5615573fec93b287b30` | `https://huggingface.co/wgsxm/PartCrafter` | `69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f` |

The model Dockerfiles and wrappers should use these pins unless a later PR re-checks and updates them deliberately.

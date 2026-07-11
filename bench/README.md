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

If a TripoSG or PartCrafter task fails twice, the runner writes `/work/output/<task-id>/failure.json` and continues the batch so the failed task record is uploaded with the successful outputs.

The canonical `meta.json` schema is enforced by `bench_harness.meta.REQUIRED_META_KEYS`.

## Local Commands

```powershell
cd bench
uv run pytest
uv run bench-harness tasks-validate ../tasks/tasks.json
uv run bench-harness output-validate <path-to-task-output-dir>
uv run bench-harness upload-local <source-dir> <target-root> runs/<model>/<gpu>/<timestamp>
uv run bench-harness upload-s3 <source-dir> s3://3dgen-runs/runs/<model>/<gpu>/<timestamp>
uv run bench-harness runpod-pods
```

`upload-s3` targets Cloudflare R2 through the S3-compatible API and requires these environment variables:

- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

### Task publish protocol

Runner task uploads configured by `RUNPOD_INCREMENTAL_S3_TARGET` use a recoverable publish protocol:

1. Validate the local success or failure contract with `bench_harness.meta`, including GLB structure,
   the declared license, and task/model IDs.
2. Upload every file to a unique `.publish-staging/<id>/` prefix with SHA-256 user metadata, then
   verify each staged object's size and hash with `HeadObject`.
3. Copy the previous canonical task prefix to `.publish-backup/<id>/` and verify the backup before
   mutating canonical keys.
4. Remove the previous `meta.json`/`failure.json` marker, copy non-marker files, remove stale files,
   and copy the new marker last. A pre-marker failure restores the complete previous prefix from backup.
5. Delete staging and backup only after the new marker is committed. Cleanup failure is reported as
   a committed publish with explicit residual prefixes; it does not roll back the valid new result.

R2 has no multi-object rename. This protocol relies on its supported S3 `HeadObject`, `CopyObject`,
source copy conditions, user metadata, and read-after-write consistency. Confirmed 2026-07-11:

- https://developers.cloudflare.com/r2/api/s3/api/
- https://developers.cloudflare.com/r2/reference/consistency/

The launcher must keep a single writer per canonical task prefix. Python/S3 operation failures restore the
backup before returning. A hard process or host termination during the short marker-free commit window cannot
run rollback; the retained `.publish-backup/<id>/` is then the manual recovery source.

`bench-harness upload-s3` without a relative task name remains a direct recursive upload for startup
and final telemetry. It is not a canonical task replacement operation.

RunPod launch commands additionally require `RUNPOD_API_KEY`:

```powershell
uv run bench-harness runpod-launch triposg ghcr.io/hitsuki-ban/3dgen-triposg@sha256:<digest> s3://3dgen-runs/runs/triposg/rtx-5090/<timestamp> --name 3dgen-triposg-wave1 --container-registry-auth-id <runpod-registry-auth-id> --network-volume-id <runpod-network-volume-id> --data-center-id <runpod-data-center-id> --startup-timeout-min <minutes>
uv run bench-harness runpod-terminate <pod-id>
```

RunPod benchmark pods mount the network volume at `/workspace` and run in Hugging Face offline mode. The volume must already contain the pinned weights:

- `/workspace/weights/TripoSG`
- `/workspace/weights/PartCrafter`
- `/workspace/weights/RMBG-1.4`

## Docker Build Cache

On Windows, Docker Desktop stores loaded images inside its C: drive WSL VHDX. To keep repeated model builds from filling C:, use the repository build wrapper from the repo root:

```powershell
.\scripts\docker-build-model.ps1 triposg
.\scripts\docker-build-model.ps1 partcrafter
```

By default it writes buildx local cache and the image archive to `.docker-build/` under the F: workspace. The build context is the repository root so cloud images can include `bench/src`, `tasks/`, and the model runner while `.dockerignore` excludes generated outputs, worktrees, and Docker cache. Load the image only when a local smoke run is needed:

```powershell
docker load -i .docker-build\images\3dgen-triposg-issue-11.tar
```

For direct build-and-run work on a machine with enough C: space, pass `-Load`:

```powershell
.\scripts\docker-build-model.ps1 triposg -Load
```

For cloud runs, push directly from buildx so Docker Desktop does not keep a loaded image copy:

```powershell
.\scripts\docker-build-model.ps1 triposg -Tag ghcr.io/hitsuki-ban/3dgen-triposg-runtime:<tag> -Push
```

After smoke runs, remove images that are no longer needed and clear build cache:

```powershell
docker rmi 3dgen/triposg:issue-11
docker builder prune -af
```

## Model Runners

Implemented runner containers:

- `models/triposr/` — TripoSR image-to-3D runner. Builds a pinned CUDA 12.8 + torch 2.7 image and writes the benchmark output contract for each task.
- `models/triposg/` — TripoSG image-to-geometry runner. Builds a pinned CUDA 12.8 + torch 2.7 image, uses pinned TripoSG/RMBG weights, and writes `LICENSES.txt` with upstream notices.
- `models/partcrafter/` — PartCrafter part-aware image-to-3D runner. Builds a pinned CUDA 12.8 + torch 2.7 image, uses pinned PartCrafter/RMBG weights, disables VLM/style-transfer API paths, and writes part meshes plus a composite `output.glb`.
- `models/trellis1/` — TRELLIS v1 image-to-3D runner. Builds a pinned CUDA 12.1 + torch 2.4 image, uses staged `TRELLIS-image-large` weights, exports canonical `output.glb`, and keeps the raw Gaussian PLY for audit.
- `models/3dtopia-xl/` — 3DTopia-XL image-to-3D runner. Builds a pinned CUDA 11.8 + Python 3.9 image, uses staged `3DTopia-XL` weights, and exports the official PBR GLB output.
- `models/trellis2/` — TRELLIS.2-4B image-to-3D runner. Builds a pinned CUDA 12.8 + torch 2.7 image, uses staged `TRELLIS.2-4B` weights plus gated HF cache dependencies, and exports the official PBR GLB output.
- `models/direct3d-s2/` — Direct3D-S2 image-to-geometry runner. Builds a pinned CUDA 12.8 + torch 2.7 image, uses staged `direct3d-s2-v-1-1` weights, and exports a geometry-only GLB plus raw OBJ.
- `models/sf3d/` — Stable Fast 3D image-to-textured-mesh runner. Builds a pinned CUDA 12.8 + torch 2.7 runtime-only image, uses staged gated weights and DINOv2 cache, and preserves the official 1024-texture no-remesh defaults.

## Local Validation Scope

The local 12GB RTX 4070 Ti validation gate is for lightweight runners first. TripoSR has already passed the two-task local E2E path. TripoSG's official decoder configuration (`num_tokens=2048`, `flash_octree_depth=9`) proved too heavy for local validation: diffusion finished, but geometry extraction did not complete after more than 10 minutes. A reduced diagnostic run (`num_inference_steps=5`, `num_tokens=1024`, `flash_octree_depth=8`) completed and exported a GLB, so TripoSG full generation is deferred to the cloud GPU phase. Apply the same rule to PartCrafter if local generation blocks progress: keep pins, buildability, runner contract, and unit tests local; move full generation evidence to the cloud run issue.

## Cost Guardrails

- Local container watchdog `MAX_RUNTIME_MIN` defaults to `60`, as specified in Issue #11. Cloud launcher `--max-runtime-min` defaults to `90`, as specified in Issue #25. Non-positive values fail fast.
- When `RUNPOD_POD_ID` is present, RunPod self-termination requires `RUNPOD_API_KEY`; missing credentials fail fast.
- Remote RunPod launch checks `clientBalance` before creating a pod. The default minimum balance is `$5`, or override it with `RUNPOD_MIN_BALANCE_USD` / `--min-balance-usd`.
- The default cloud GPU priority is RTX 5090 followed by RTX 4090, with `allowedCudaVersions=("12.8",)`.
- Private GHCR images require an explicit RunPod `--container-registry-auth-id`; the launcher writes it to `containerRegistryAuthId` in the pod payload.
- Cloud benchmark launches require an explicit RunPod `--network-volume-id`, `--data-center-id`, and `--startup-timeout-min`. The launcher writes `networkVolumeId`, constrains pod placement to the same single data center, mounts the volume at `/workspace`, and injects `/workspace/weights/...` model paths instead of using baked image weight layers.
- After pod creation, the launcher polls `GET /pods/<id>` until the pod has `publicIp`, a port mapping for container SSH port `22`, and a reachable mapped TCP port. If startup exceeds `--startup-timeout-min`, it terminates the pod before the container-side watchdog can start.
- The launcher injects `RUNPOD_API_KEY` plus the three R2 environment variables into the pod so the runner can self-terminate and upload before exit.
- The pod command writes `runpod-status.json`, uploads the output directory even if the model runner exits non-zero, and then attempts best-effort self-termination. Upload/status failures take precedence over the runner exit code because a missing R2 report is an infrastructure failure, not a model result.
- CLI output strips RunPod `env` fields before printing pod responses. Do not use raw RunPod pod JSON in reports because it can contain injected secrets.
- TripoSG and PartCrafter retry each failed task once; after the retry fails, they write `failure.json` instead of aborting the whole 25-task batch.

## Source Pins Checked On 2026-07-08

Primary sources checked before this harness split:

| Model | Code source | Code commit | Weights source | Weights revision |
|---|---|---:|---|---:|
| TripoSR | `https://github.com/VAST-AI-Research/TripoSR` | `107cefdc244c39106fa830359024f6a2f1c78871` | `https://huggingface.co/stabilityai/TripoSR` | `5b521936b01fbe1890f6f9baed0254ab6351c04a` |
| TripoSG | `https://github.com/VAST-AI-Research/TripoSG` | `fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c` | `https://huggingface.co/VAST-AI/TripoSG` | `2c1c516d22d58db486a058d98d31bb6177344e06` |
| PartCrafter | `https://github.com/wgsxm/PartCrafter` | `3d773bf02fad51c7ab31a5615573fec93b287b30` | `https://huggingface.co/wgsxm/PartCrafter` | `69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f` |

The model Dockerfiles and wrappers should use these pins unless a later PR re-checks and updates them deliberately.

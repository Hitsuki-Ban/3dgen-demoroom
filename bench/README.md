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
uv run bench-harness upload-s3 <top-level-telemetry-dir> s3://3dgen-runs/runs/<model>/<gpu>/<timestamp>
uv run bench-harness runpod-pods
```

`upload-s3` targets Cloudflare R2 through the S3-compatible API and requires these environment variables:

- `R2_ENDPOINT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

### Task publish protocol

Runner task uploads configured by `RUNPOD_INCREMENTAL_S3_TARGET` use a recoverable publish protocol:

1. Validate the local success or failure contract with `bench_harness.meta`, including GLB structure,
   the declared license, and exact `runs/<model-id>/.../<task-id>` target IDs. Acquire a persistent
   per-task R2 lock before reading or mutating canonical state: create it with conditional
   `PutObject If-None-Match: *`, or compare-and-swap a `released` lock to `owned` with the prior ETag
   in `PutObject If-Match`. Every state transition writes a fresh transition ID in the body, preventing
   protocol-level ETag reuse.
2. Upload every file to a unique `.publish-staging/<id>/` prefix with SHA-256 user metadata, then
   verify its size and SHA metadata round-trip with `HeadObject`. The SHA value is local provenance
   metadata; `HeadObject` does not download or independently hash remote object bytes.
3. Copy the previous canonical task prefix to `.publish-backup/<id>/` and verify the backup before
   mutating canonical keys.
4. Remove the previous `meta.json`/`failure.json` marker, copy non-marker files, remove stale files,
   and copy the new marker last. Any catchable interruption in this mutation window attempts to restore
   the complete previous prefix from backup before propagating the original error.
5. Delete staging and backup only after the new marker is committed. Cleanup failure is reported as
   a committed publish with explicit residual prefixes; it does not roll back the valid new result.
   Release the task lock only after canonical state is known to be valid, using the owned ETag to
   compare-and-swap `owned` to `released`. The protocol never deletes lock objects, so a delayed old
   release cannot delete a newer owner's lock. Rollback failure or hard process loss leaves the state
   `owned` so another writer cannot overwrite the recovery evidence.

R2 has no multi-object rename. This protocol relies on its supported S3 `HeadObject`, `CopyObject`,
conditional `PutObject`, source copy conditions, user metadata, and per-object read-after-write consistency.
Confirmed 2026-07-12:

- [R2 S3 API compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
- [R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/)
- [R2 conditional copy semantics](https://developers.cloudflare.com/r2/api/s3/extensions/)
- [S3 `HeadObject`](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/head_object.html)

This is not a multi-object transaction or reader snapshot. The conditional task lock enforces one repository
writer, but readers must not build a publication snapshot concurrently with a task commit. A missing marker
means publish-in-progress and must be skipped/retried; reading a marker once does not pin the other keys to that
generation. Run snapshot validation only after the publisher returns. These guarantees apply to direct R2
S3/Workers-binding reads, not a custom-domain cache, whose invalidation is a separate deployment concern.

Catchable Python/S3 failures restore the backup before returning. A hard process or host termination during
the marker-free commit window cannot run rollback; `.publish-backup/<id>/`, `.publish-staging/<id>/`, and the
retained `.publish-locks/<task-id>.json` are then the manual recovery evidence. Verify/restore canonical state
before conditionally transitioning that exact owned ETag to `released`. Do not delete or overwrite the lock.

`bench-harness upload-s3` without a relative task name accepts top-level startup/final telemetry files only.
The RunPod launcher writes those files under `/work/runpod-telemetry`; task outputs stay under `/work/output`
and must never enter this direct-upload path.

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
- Before creating a pod, the launcher creates a unique R2 ownership record with a launch token. After SSH becomes reachable it offers `launcher -> handoff_pending`; the container must acknowledge `handoff_pending -> runtime` before the launcher releases ownership. At either handoff timeout boundary, competing cleanup/acknowledgement CAS operations choose exactly one owner.
- Normal launcher/runtime cleanup records `deleting_<owner>` with CAS before DELETE. A runtime that already holds authoritative `runtime` ownership still attempts idempotent DELETE if the audit-marker write is unavailable; a launcher with uncertain ownership does not race it and relies on the server `terminateAfter` deadline. A runtime that observes its own `deleting_runtime` state may resume DELETE after restart. Cleanup failures preserve the original error and report the pod ID plus `runpodctl pod delete <id>` on stderr.
- Once the ownership CAS reaches `runtime`, `bench_harness.runpod_runtime` proceeds with the model command. Model runners never call the RunPod API. Every image uses `bench_harness.container_entrypoint` and requires the explicit `runner` or `runpod` execution mode.
- When `RUNPOD_POD_ID` is present, the runtime owner requires `RUNPOD_API_KEY`; missing credentials fail fast and report the manual cleanup command.
- Remote RunPod launch checks `clientBalance` before creating a pod. The default minimum balance is `$5`, or override it with `RUNPOD_MIN_BALANCE_USD` / `--min-balance-usd`.
- The default cloud GPU priority is RTX 5090 followed by RTX 4090, with `allowedCudaVersions=("12.8",)`.
- Pod creation uses RunPod's GraphQL on-demand mutation so the request includes a server-side `terminateAfter` deadline while preserving `gpuTypeIdList` and `allowedCudaVersions`. The deadline is startup timeout + model runtime budget + a 30-minute evidence grace, and remains effective if the create response, launcher, or runtime process is lost.
- Private GHCR images require an explicit RunPod `--container-registry-auth-id`; the launcher writes it to `containerRegistryAuthId` in the pod payload.
- Cloud benchmark launches require an explicit RunPod `--network-volume-id`, `--data-center-id`, and `--startup-timeout-min`. The launcher writes `networkVolumeId`, constrains pod placement to the same single data center, mounts the volume at `/workspace`, and injects `/workspace/weights/...` model paths instead of using baked image weight layers.
- After pod creation, the launcher polls `GET /pods/<id>` until the pod has `publicIp`, a port mapping for container SSH port `22`, and a reachable mapped TCP port. Timeout, HTTP, response parsing, and TCP probe exceptions all pass through the same startup cleanup path.
- The launcher injects `RUNPOD_API_KEY` plus the three R2 environment variables into the pod so the runtime owner can persist evidence and terminate the pod.
- The runner publishes each task through the staged task protocol. Before SSH, handoff, or model execution, the runtime truncates `runpod-runner.log` and replaces any prior run's terminal marker with a status-only `runpod-status.json` PUT using `status: starting`; failure keeps lifecycle ownership with the launcher. Runtime telemetry stays under `/work/runpod-telemetry`, while model task output stays under `/work/output`. After the runner returns, the runtime uploads a `finalizing` status (with provisional `outcome`) in a telemetry-only sweep, then replaces only `runpod-status.json` with terminal `ok`/`failed`. A failed telemetry sweep triggers a best-effort `finalizing` status PUT. A terminal PUT response can be lost after R2 committed it, but terminal publication is attempted only after the full telemetry sweep completed. Cleanup and DELETE are attempted only after those evidence operations. Upload/status failures take precedence over the runner exit code; termination failures never hide the earlier failure.
- A task timeout kills and waits for the inference process group, closes its log, writes `failure.json` with the available output tail, uploads the task evidence, and then propagates `TimeoutError` to the runtime owner. Timeout is never retried.
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

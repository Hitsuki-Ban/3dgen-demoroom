# RunPod large artifact handling: Codex notes

- Checked: 2026-07-08 JST
- Scope: RunPod Pods startup speed, Docker image pulls, large Hugging Face weight loading, and cache layout for the cloud benchmark path in Issue #25.

## Conclusion

Do not keep iterating on the current "weights baked into GHCR image layers" path for TripoSG and PartCrafter. The first TripoSG cloud attempt already proved that private registry auth works, but the pod stayed in the pre-container image pull phase while fetching a multi-GB layer. That phase is outside the runner's `MAX_RUNTIME_MIN` watchdog, so it can burn GPU time before any benchmark code starts.

Recommended next path:

1. Build smaller runtime images that contain CUDA/Python dependencies, model source code, runners, and task files, but not model snapshots.
2. Create a RunPod network volume in the target data center and pre-populate exact pinned model revisions there.
3. Mount that volume into benchmark pods and make runners read weights from explicit volume paths.
4. Keep R2 only for benchmark outputs and small manifests, not for hot model reads.

This trades one controlled staging job for much lower repeated launch risk. It also keeps private/licensed model redistribution risk lower than making GHCR packages public.

## What RunPod documents imply

RunPod exposes three relevant Pod storage types:

- **Container disk** is temporary and cleared when a pod stops. It is appropriate for OS files, temp files, and ephemeral caches, not benchmark-critical model snapshots.
- **Volume disk** is mounted at `/workspace` and survives pod stop/restart, but is deleted when the pod is terminated. It can help during debugging, but not for reusable benchmark cache across one-off pods.
- **Network volume** persists independently of compute, can be shared across pods, and is the intended reusable storage primitive for shared data, datasets, and checkpoints.

Official network volume docs also describe a create-by-data-center flow and a REST create endpoint. That matters because the cache must live in a data center where the target GPU type is available; otherwise the launcher can allocate a pod that cannot attach the desired volume.

RunPod's Serverless model caching tutorial is not the same product path as Pods, but it demonstrates the same operational pattern we want: a handler locates a cached model locally and uses offline mode to avoid re-downloading during cold starts. For Pods, the analogous implementation is a mounted network volume plus fail-fast checks for expected revision marker files.

## Community and template practice

RunPod-maintained worker templates use two patterns that map well to this project:

- `runpod-workers/worker-vllm` has a `BASE_PATH` build argument for where the Hugging Face cache and model live. Its default is `/runpod-volume`, so attaching network storage naturally redirects the model/cache path there.
- `runpod-workers/worker-tgi` documents a `DOWNLOAD_MODEL=false` mode. In that mode, the Docker image does not include model weights and the user must pre-download weights to network storage, with Hugging Face cache env vars pointed at `/runpod-volume/huggingface-cache`.

The pattern is not "download weights on every pod boot." It is "preload exact weights once, then start inference pods against an already-populated local path."

Community issue traffic around RunPod workers also treats model download/cache behavior as an operational concern separate from inference code. The actionable lesson for us is to make cache miss obvious and cheap: a pod should fail immediately with a clear message if the mounted volume lacks the pinned revision, rather than silently starting a multi-GB download on a paid GPU.

## Hugging Face transfer practice

Hugging Face Hub now documents `HF_HUB_ENABLE_HF_TRANSFER` as deprecated because transfers go through `hf-xet` when available. For a staging pod, use current `huggingface_hub` plus `hf-xet`, set cache locations under the mounted volume, and set `HF_XET_HIGH_PERFORMANCE=1` only during the staging download job if the node has enough CPU/disk headroom.

Recommended staging environment:

```bash
export HF_HOME=/workspace/hf
export HF_HUB_CACHE=/workspace/hf/hub
export HF_XET_CACHE=/workspace/hf/xet
export HF_XET_HIGH_PERFORMANCE=1
```

Recommended runtime environment after the volume is warm:

```bash
export HF_HOME=/workspace/hf
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

For our runners, the more important piece is not the generic Hugging Face cache path but the explicit model snapshot path. TripoSG and PartCrafter now require environment variables pointing at volume-backed directories:

- `/workspace/weights/TripoSG`
- `/workspace/weights/PartCrafter`
- `/workspace/weights/RMBG-1.4`

## Implementation status in current follow-up branch

Implemented:

- `bench-harness runpod-launch` requires `--network-volume-id`.
- Pod payloads include `networkVolumeId` and mount the volume at `/workspace`.
- Pod payloads require one explicit `--data-center-id` and set `dataCenterPriority=custom` so placement stays with the volume.
- `bench-harness runpod-launch` requires `--startup-timeout-min`; if a reachable mapped SSH TCP port does not appear before the timeout, it terminates the pod.
- Pod env includes Hugging Face offline mode and explicit model weight paths under `/workspace/weights`.
- TripoSG and PartCrafter Dockerfiles no longer download model snapshots into image layers.
- TripoSG and PartCrafter runners fail fast when explicit weight path environment variables are missing.
- Runtime images install and start `openssh-server` before benchmark execution, so launcher readiness waits for a real reachable container SSH port.
- Pod env includes `RUNPOD_INCREMENTAL_S3_TARGET`, and model runners upload each completed or final-failed task directory to R2 immediately under that task id.

Created/staged volume:

- ID: `wnqijpazd5`
- Name: `3dgen-wave1-weights-eu-ro-1-20260708T155503Z`
- Data center: `EU-RO-1`
- Size: 30GB
- Created: 2026-07-08
- Staged weights report: `runs/staging/20260708T155503Z/network-volume-wnqijpazd5.json`

Retired volume:

- `cwcjs6bz6j` in `US-NC-1` was deleted after EU-RO-1 staging succeeded, because actual create capacity in US-NC-1 was unavailable.

Weight-free runtime package:

- `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1`
- Digest: `sha256:d4bc56e23a07bea440eff269216998d790c1b5af697ec335fd74e8ed17a5d332`
- The package was split from the historical `3dgen-triposg` package so it does not expose baked-weight tags when made public.
- Current status: still private; anonymous GHCR manifest probe returned HTTP 401.
- GitHub documents changing a package to public as irreversible, so this toggle should only happen after explicit Fable/owner approval.
- A private-auth retry with this package on `EU-RO-1` reached `publicIp` and an SSH port mapping, but TCP to SSH stayed closed and RunPod later returned `pod not found` before R2 telemetry. The runtime images did not install/start an SSH daemon, so the launcher-side SSH readiness gate could not succeed.
- The SSH-enabled image fixed container readiness and reached active inference, but pod disappearance after 22 completed task metadata files left R2 empty because upload still happened only at the end.
- Current TripoSG retry image: `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1-ssh-incremental` at digest `sha256:5a3088fa4038648d0f5b19200c03a5ec45fb206947503ac24dafb6443a6403f8`.

## Recommended implementation plan

1. Make benchmark runners validate the staging report or expected weight files before starting the first task.
2. Keep the old baked-weight images only as historical artifacts; do not spend more GPU time testing them.
3. Keep the launcher command observable: upload a `runpod-status.json` file even when the model runner exits non-zero, then terminate the pod from local monitoring if self-termination does not complete.
4. Upload each task result incrementally to R2. Final upload is still useful as a sweep, but it cannot be the only persistence path on preempted or disappearing pods.
5. Retry the SSH + incremental TripoSG runtime on the same private package path. If the rebuilt private package still stalls before SSH readiness, either make the package public after explicit approval and verify anonymous manifest access, or run a tiny diagnostic image against the same data center/volume to isolate RunPod machine/volume startup from GHCR runtime image pull.

## Candidate staging commands

This should run on a cheap RunPod pod in the same data center as the network volume, not on the final benchmark pod:

```bash
uv pip install --system "huggingface_hub[hf_xet]"

python3 - <<'PY'
from pathlib import Path
from huggingface_hub import snapshot_download

downloads = [
    ("VAST-AI/TripoSG", "2c1c516d22d58db486a058d98d31bb6177344e06", "/workspace/weights/TripoSG"),
    ("wgsxm/PartCrafter", "69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f", "/workspace/weights/PartCrafter"),
    ("briaai/RMBG-1.4", "2ceba5a5efaec153162aedea169f76caf9b46cf8", "/workspace/weights/RMBG-1.4"),
]

for repo_id, revision, local_dir in downloads:
    Path(local_dir).parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(repo_id=repo_id, revision=revision, local_dir=local_dir)
PY
```

After staging, run a no-GPU or short-GPU smoke pod that mounts the same volume and checks:

```bash
test -f /workspace/weights/TripoSG/model_index.json
test -f /workspace/weights/RMBG-1.4/config.json
du -sh /workspace/weights /workspace/hf
```

Adjust file checks per model if upstream layouts differ.

## Operational notes

- Use `runpodctl pod list` or `bench-harness runpod-pods` for status. Avoid raw `runpodctl pod get` in logs because it prints pod environment values.
- Keep the launcher-side pre-container watchdog tied to a reachable mapped SSH port. `publicIp` alone can appear before the container is actually usable.
- Prefer one model per cloud launch until cache behavior is proven.
- Store outputs and run manifests in R2. Do not put frequently-read model weights on R2 for inference unless a later benchmark proves R2 throughput is competitive from the chosen RunPod data center.

## Sources

- RunPod Network Volumes docs: https://docs.runpod.io/storage/network-volumes (checked 2026-07-08)
- RunPod Pod storage options: https://docs.runpod.io/pods/storage/types (checked 2026-07-08)
- RunPod Create Pod API: https://docs.runpod.io/api-reference/pods/POST/pods (checked 2026-07-08)
- RunPod Serverless model caching tutorial: https://docs.runpod.io/tutorials/serverless/model-caching-text (checked 2026-07-08)
- RunPod Dockerfile tutorial: https://docs.runpod.io/tutorials/introduction/containers/create-dockerfiles (checked 2026-07-08)
- RunPod worker-vLLM README: https://github.com/runpod-workers/worker-vllm (checked 2026-07-08)
- RunPod worker-TGI README: https://github.com/runpod-workers/worker-tgi (checked 2026-07-08)
- Hugging Face Hub environment variables: https://huggingface.co/docs/huggingface_hub/en/package_reference/environment_variables (checked 2026-07-08)
- GitHub package access control and visibility: https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility (checked 2026-07-09)

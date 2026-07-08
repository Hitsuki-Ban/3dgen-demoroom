# 2026-07 Cloud Wave 1

Checked: 2026-07-08
Issue: #25

## Status

Implemented the local code needed for the first RunPod/R2 cloud wave and pushed the first two cloud images to GHCR. The first TripoSG RunPod launch reached pod allocation, but did not reach container execution because image pull was too slow.

- RunPod API key is present as a GitHub secret: `RUNPOD_API_KEY`.
- R2 is enabled. Cloudflare API created bucket `3dgen-runs` on 2026-07-08T04:35:35Z with location `APAC`, storage class `Standard`, jurisdiction `default`.
- Cloudflare R2 object API probe passed: wrote, listed, and deleted `_codex-api-probe.txt`.
- R2 S3-compatible upload probe passed through `bench-harness upload-s3`, then `_codex-s3-probe/probe.txt` was deleted through Cloudflare REST API.
- GitHub secrets are set: `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`. They were rotated again on 2026-07-08T12:43Z after a fresh R2 S3 token was created.
- Local `.env` now exposes `RUNPOD_API_KEY`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` for direct launcher use.
- R2 S3-compatible upload probe passed again with the rotated key: uploaded and deleted one object under `_codex-s3-probe/<timestamp>/`.
- The prior R2 S3 key was revoked by the owner.
- GHCR packages were created as private by default. RunPod private registry auth has been provisioned as `cmrc1l2gc00847uotrnjn2des`.
- RunPod pod `6o5yduivsud4yt` was launched for TripoSG at 2026-07-08T12:50:25Z and terminated manually after log inspection; `bench-harness runpod-pods` then returned `[]`.
- There are no cloud artifacts from that pod because the container never reached runner execution.
- The old empty RunPod network volume `b01dms1lva` in `US-IL-1` was deleted after Fable's review noted that volume placement must follow actual 5090 data center availability.
- Former RunPod network volume: `cwcjs6bz6j` (`3dgen-wave1-weights-us-nc-1`) in data center `US-NC-1`, size 30GB. It was CPU-staged successfully with TripoSG, PartCrafter, and RMBG pinned weights. R2 staging report: `runs/staging/20260708T144842Z/network-volume-cwcjs6bz6j.json`.
- A paid TripoSG runtime-only launch on `US-NC-1` reached public IP, then lost public IP/port mappings while `/pods` still reported `RUNNING`; it was manually terminated with no R2 benchmark artifacts. This exposed a launcher observability gap: runner failures did not upload a status report because the command used `runner && upload-s3`.
- A follow-up TripoSG retry after the status-upload fix did not create a pod. RunPod returned HTTP 500 from `POST /pods` with body `create pod: There are no instances currently available`. `bench-harness runpod-pods` returned `[]` afterward.
- EU-RO-1 was validated with a 10GB temporary network volume and short RTX 4090 smoke pod; both temporary resources were deleted. A new 30GB EU-RO-1 volume `wnqijpazd5` was staged successfully with TripoSG, PartCrafter, and RMBG pinned weights. R2 staging report: `runs/staging/20260708T155503Z/network-volume-wnqijpazd5.json`.
- The old US-NC-1 volume `cwcjs6bz6j` was deleted after EU-RO-1 staging succeeded, avoiding double network-volume storage cost while US-NC-1 had no actual create capacity.
- A paid TripoSG runtime-only launch on EU-RO-1 created pod `sgoerg5ya0v8hw` on RTX 4090 and reached `publicIp`, but mapped SSH port 22 never became reachable and R2 remained empty. It was terminated at 2026-07-08T16:24Z, and active pods returned to `[]`.
- A paid retry with the split TripoSG weight-free runtime package and private registry auth created pod `il8q7manajir88` on EU-RO-1; `publicIp` and SSH port mapping appeared, but TCP to SSH stayed closed, RunPod later returned `pod not found` during startup polling, and R2 remained empty. This exposed that the runtime images did not install/start an SSH daemon, so the launcher-side SSH readiness gate could not succeed.
- A paid retry with SSH daemon support created pod `jlnk4q5rjjh3m3` on EU-RO-1. SSH became reachable and the runner reached 22 completed task metadata files before the pod disappeared. R2 stayed empty because the command still uploaded only once at the end, so mid-run pod loss discarded otherwise usable task outputs.
- The launcher now injects `RUNPOD_INCREMENTAL_S3_TARGET`, and TripoSG/PartCrafter runners upload each completed or failed task directory to R2 under that task id. Incremental upload failures fail the run as infrastructure failures instead of being treated as model inference failures.

## GHCR Images

| Model | Image | Digest | Package visibility |
| --- | --- | --- | --- |
| TripoSG | `ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1` | `sha256:20683da63af15a45e64d6f4dfcb2c92763b6bc33f71bb046c0c852c2aae7e6b9` | private |
| PartCrafter | `ghcr.io/hitsuki-ban/3dgen-partcrafter:2026-07-cloud-wave1` | `sha256:b84791ae147f43dc5556bb8d853b2b16f311c657a96fecdff6f1706bd3b2df9b` | private |
| TripoSG runtime-only | `ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1-runtime-volume` | `sha256:d210db2e5c0aa22cc788129de6e4a8484e0380346ce1f9d2169ce25dcd5d640e` | private |
| PartCrafter runtime-only | `ghcr.io/hitsuki-ban/3dgen-partcrafter:2026-07-cloud-wave1-runtime-volume` | `sha256:bb9e7bff54ca1688c1584f1de0e12c11153caa3d4a32f2073068e9ef27ce0eb0` | private |
| TripoSG weight-free runtime package | `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1` | `sha256:d4bc56e23a07bea440eff269216998d790c1b5af697ec335fd74e8ed17a5d332` | private; package was created separately from historical baked-weight tags, but GitHub package visibility still needs UI change to become anonymous-pullable |
| TripoSG weight-free runtime, SSH + incremental upload | `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1-ssh-incremental` | `sha256:5a3088fa4038648d0f5b19200c03a5ec45fb206947503ac24dafb6443a6403f8` | private; use `containerRegistryAuthId` |

## Implemented

- `bench-harness upload-s3` uploads a run directory to `s3://<bucket>/<prefix>` through Cloudflare R2 S3-compatible credentials.
- Empty upload relative names now omit dot path segments from S3 object keys.
- `bench-harness runpod-launch` builds a RunPod Pods API payload for TripoSG or PartCrafter, checks `clientBalance`, then creates an on-demand pod.
- `bench-harness runpod-pods` and `bench-harness runpod-terminate` provide the GET /pods confirmation and cleanup path for the later GPU pass.
- TripoSG and PartCrafter Docker images now build from the repository root context and include `bench/src` plus `tasks/` so pod startup can run all 25 tasks and upload results.
- TripoSG and PartCrafter runners retry each failed task once and write `failure.json` after the retry fails, allowing the remaining 25-task batch to continue.
- Root `.dockerignore` excludes `.git`, `.worktrees`, `.docker-build`, `outputs`, and local Python/Node build directories from model image contexts.
- RunPod HTTP calls now set a project User-Agent. Without it, RunPod's fronting protection can reject Python `urllib` calls with HTTP 403 / error code 1010.
- `bench-harness runpod-pods` now accepts the RunPod REST API's JSON array response. The previous object-only parser failed on the empty-pod `[]` response.
- The cloud launcher now requires `--network-volume-id`, injects `networkVolumeId`, mounts the volume at `/workspace`, and sets model weight paths under `/workspace/weights`.
- The cloud launcher also requires `--data-center-id` and writes `dataCenterIds` / `dataCenterPriority=custom`, so pod placement stays in the same data center as the network volume.
- The cloud launcher now has a pre-container startup watchdog: it polls `GET /pods/<id>` until `publicIp` appears and the mapped SSH TCP port is reachable, and terminates the pod if `--startup-timeout-min` expires first.
- TripoSG and PartCrafter cloud images are now runtime-only with respect to model weights; their Dockerfiles no longer download Hugging Face snapshots into image layers.
- TripoSG and PartCrafter runners now fail fast unless explicit weight path environment variables are present.
- RunPod cloud commands now write `runpod-status.json`, upload the output directory even when the runner exits non-zero, and then attempt best-effort self-termination. Upload/status failures take precedence over runner failures because a missing R2 report is an infrastructure failure.
- `bench-harness runpod-launch` and `runpod-pods` now strip RunPod `env` fields before printing pod responses, so local logs do not contain injected R2 or RunPod secrets.
- RunPod HTTP errors now include the response body in the raised exception, which exposed the 2026-07-08T15:46Z retry failure as a capacity miss instead of an opaque HTTP 500.
- Startup polling now reports a pod that disappears before SSH readiness as an explicit startup failure instead of surfacing a raw `GET /pods/<id>` HTTP 404 stack trace.
- TripoSG and PartCrafter runtime images now install `openssh-server`, and the RunPod start command starts SSH before running the benchmark so the launcher-side SSH readiness gate reflects actual container readiness.
- The RunPod payload injects `RUNPOD_INCREMENTAL_S3_TARGET`, and the model runners upload each task directory immediately after success or final failure. The final full-run upload remains as a completion sweep.
- Successful task output upload failures are no longer caught by model retry handling; they now stop the run as upload infrastructure failures without re-running a successful generation.

## TripoSG Launch Attempt

Command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg@sha256:20683da63af15a45e64d6f4dfcb2c92763b6bc33f71bb046c0c852c2aae7e6b9 `
  s3://3dgen-runs/runs/triposg/rtx-5090/20260708T125024Z `
  --name 3dgen-triposg-wave1-20260708T125024Z `
  --min-balance-usd 12 `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id <runpod-network-volume-id> `
  --data-center-id <runpod-data-center-id> `
  --startup-timeout-min <minutes>
```

Observed:

- Pod id: `6o5yduivsud4yt`
- Cost reported by RunPod: about `$0.99/hr` to `$1.02/hr`
- GPU: `RTX 5090 x1`
- R2 prefix: `runs/triposg/rtx-5090/20260708T125024Z`
- `publicIp` stayed empty and `runpodctl ssh info` reported `pod not ready`, so the pod never became SSH-ready.
- RunPod Console Logs tab showed the pod was still fetching the private GHCR image. Visible system log excerpts were saved locally under gitignored `.docker-build/logs/runpod-6o5yduivsud4yt-visible-logs*.txt`.
- Representative log lines showed a layer `e9170f051478` downloading an `8.073GB` payload at roughly tens of MB/minute, and another layer `9a9be3767ce7` retrying. The console also repeated `create container: still fetching image`.
- The pod was terminated before container execution to keep spend bounded. R2 object count under the run prefix remained `0`.

Conclusion: private registry auth worked far enough for RunPod to begin pulling the image, but the current image/layer shape is too heavy for the intended 90-minute wave guardrail. The next run should reduce or pre-warm image transfer before launching another full 25-task pod.

See also: [RunPod large artifact handling: Codex notes](../research/runpod-large-artifacts-codex.md). The implemented path now uses runtime-only images plus a pre-populated RunPod network volume instead of baked-weight GHCR layers.

## TripoSG Runtime-Only Launch Attempt

Command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1-runtime-volume `
  s3://3dgen-runs/runs/triposg/wave1/20260708T145633Z `
  --name 3dgen-triposg-wave1-20260708T145633Z `
  --min-balance-usd 12 `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id cwcjs6bz6j `
  --data-center-id US-NC-1 `
  --startup-timeout-min 25
```

Observed:

- Pod id: `3n74xwryczc907`
- Created at: 2026-07-08T14:56:33Z
- Cost reported by RunPod: `$0.99/hr`
- Data center: `US-NC-1`
- Network volume: `cwcjs6bz6j`
- R2 prefix: `runs/triposg/wave1/20260708T145633Z/`
- Startup watchdog passed: `publicIp` appeared at about 2026-07-08T14:58:58Z.
- R2 object count stayed `0`.
- During monitoring, `publicIp` and `portMappings` disappeared while `/pods` still showed `desiredStatus=RUNNING`; SSH was unavailable.
- The pod was manually terminated to stop spend.

Conclusion: the runtime-only image fixed the pre-container pull delay, but the command did not produce enough failure telemetry. The launcher command now uploads a `runpod-status.json` file even when the runner fails, and treats upload/status failures as infrastructure failures, so the next paid retry should produce an R2 status artifact instead of a blank prefix.

## TripoSG Status-Fix Retry

Documented at 2026-07-08T15:46Z after rechecking active pods.

Command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1-runtime-volume `
  s3://3dgen-runs/runs/triposg/wave1/<timestamp> `
  --name 3dgen-triposg-wave1-statusfix-<timestamp> `
  --min-balance-usd 12 `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id cwcjs6bz6j `
  --data-center-id US-NC-1 `
  --startup-timeout-min 25 `
  --allowed-cuda-version 13.0 `
  --allowed-cuda-version 12.9 `
  --allowed-cuda-version 12.8
```

Observed:

- RunPod rejected creation at `POST /pods` before any pod id was returned.
- The initial CLI attempt surfaced only `HTTP Error 500: Internal Server Error`.
- A diagnostic retry using the same payload captured the response body: `create pod: There are no instances currently available`.
- `bench-harness runpod-pods` returned `[]` after the failure, so no paid pod was left running.
- No R2 benchmark prefix was created because the container never started.

Conclusion at that point: the blocker was RunPod capacity in the only warmed network-volume data center (`US-NC-1`), not the launcher payload or credentials. The next step was to wait for capacity change or use another network-volume-supported data center after staging weights there.

## EU-RO-1 Staging and Runtime-Only Retry

Documented at 2026-07-08T16:24Z after terminating the stalled GPU pod and rechecking active pods.

EU-RO-1 readiness checks:

- `runpodctl datacenter list` showed EU-RO-1 RTX 4090 stock as `Medium`.
- A 10GB temporary network volume in EU-RO-1 was created and deleted successfully.
- A short RTX 4090 smoke pod using that temporary volume was created and deleted successfully.

Staging:

- Current retained volume: `wnqijpazd5`
- Name: `3dgen-wave1-weights-eu-ro-1-20260708T155503Z`
- Data center: `EU-RO-1`
- Size: 30GB
- Staging pod: CPU, `$0.06/hr`, self-terminated.
- R2 report: `runs/staging/20260708T155503Z/network-volume-wnqijpazd5.json`
- Report status: `ok`
- Downloaded payloads:
  - `VAST-AI/TripoSG`: 36 files, 7,946,497,514 bytes
  - `wgsxm/PartCrafter`: 36 files, 3,973,454,051 bytes
  - `briaai/RMBG-1.4`: 63 files, 842,221,152 bytes

Runtime-only TripoSG retry:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1-runtime-volume `
  s3://3dgen-runs/runs/triposg/wave1/20260708T155725Z `
  --name 3dgen-triposg-wave1-eu-ro-1-20260708T155725Z `
  --min-balance-usd 12 `
  --gpu-type-id "NVIDIA GeForce RTX 4090" `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id wnqijpazd5 `
  --data-center-id EU-RO-1 `
  --startup-timeout-min 25 `
  --allowed-cuda-version 13.0 `
  --allowed-cuda-version 12.9 `
  --allowed-cuda-version 12.8
```

Observed:

- Pod id: `sgoerg5ya0v8hw`
- Created at: 2026-07-08T15:57:26Z
- Cost reported by RunPod: `$0.69/hr`
- GPU: RTX 4090 x1
- Data center: `EU-RO-1`
- Network volume: `wnqijpazd5`
- R2 prefix: `runs/triposg/wave1/20260708T155725Z/`
- `publicIp` and port mapping appeared, but TCP to the mapped SSH port stayed closed through the 25-minute startup window.
- R2 object count stayed `0`.
- The pod was terminated manually at 2026-07-08T16:24Z; `bench-harness runpod-pods` then returned `[]`.

Conclusion: EU-RO-1 has usable 4090 capacity and the network volume is staged, but `publicIp` alone is not a valid startup readiness signal. The launcher now waits for a reachable mapped SSH TCP port before considering startup complete. If the next attempt still times out before SSH is reachable, the remaining bottleneck is likely private GHCR runtime image pull or container bootstrap, not model weights.

## Weight-Free Runtime Package Split

Documented at 2026-07-08T16:47Z after pushing the package and clearing local Docker cache.

- Pushed TripoSG's current runtime-only Dockerfile output to a new package name that has never contained baked model weights: `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1`.
- Digest: `sha256:d4bc56e23a07bea440eff269216998d790c1b5af697ec335fd74e8ed17a5d332`.
- The package is still `private` in GitHub Packages immediately after push.
- Anonymous manifest probe returned HTTP 401 for `https://ghcr.io/v2/hitsuki-ban/3dgen-triposg-runtime/manifests/2026-07-cloud-wave1`, so RunPod still needs registry auth until visibility is changed.
- REST attempts against `/user/packages/container/3dgen-triposg-runtime/visibility` returned 404, and GraphQL has no visible container package visibility mutation in the current schema. Treat public visibility as a GitHub UI step unless Fable has another package-management path.
- GitHub documents package public visibility as irreversible; Fable/owner approval is required before toggling this package to public.
- Docker daemon was cleaned afterward: `docker system df` returned `0` images, `0` containers, `0` build cache.

Conclusion: the package split is ready for a public runtime-only path, but it has not yet removed private GHCR pull from RunPod because GitHub Packages visibility is still private.

## Weight-Free Runtime Private-Auth Retry

Documented at 2026-07-08T17:12Z after the launcher process exited and active pods/R2 were rechecked.

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg-runtime@sha256:d4bc56e23a07bea440eff269216998d790c1b5af697ec335fd74e8ed17a5d332 `
  s3://3dgen-runs/runs/triposg/wave1/20260708T170026Z `
  --name 3dgen-triposg-wave1-runtimepkg-20260708T170026Z `
  --min-balance-usd 12 `
  --gpu-type-id "NVIDIA GeForce RTX 4090" `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id wnqijpazd5 `
  --data-center-id EU-RO-1 `
  --startup-timeout-min 25 `
  --allowed-cuda-version 13.0 `
  --allowed-cuda-version 12.9 `
  --allowed-cuda-version 12.8
```

Observed:

- Pod id: `il8q7manajir88`
- Cost reported by RunPod: `$0.69/hr`
- GPU: RTX 4090 x1
- Data center: `EU-RO-1`
- Network volume: `wnqijpazd5`
- R2 prefix: `runs/triposg/wave1/20260708T170026Z/`
- `publicIp` appeared as `213.173.108.23`; SSH port mapping appeared as container port `22` -> host port `15821`.
- TCP checks to the mapped SSH port stayed closed.
- RunPod later returned `GET /pods/il8q7manajir88` as HTTP 404 with body `{"error":"pod not found","status":404}` while startup polling was still waiting.
- R2 object count under the run prefix stayed `0`.
- Active pods after the failure: `[]`.
- Balance after the failure: `$18.5332833593`.

Conclusion: the split weight-free runtime package plus private registry auth reached `publicIp` and port mapping, but the runtime image did not provide an SSH daemon for the launcher readiness gate. The image and start command now install/start SSH before benchmark execution, while the launcher also turns a disappearing pod into an explicit startup failure with last-observed pod state.

## SSH-Enabled Runtime Retry

Documented at 2026-07-09T03:18Z after the pod disappeared and R2 was rechecked.

Image:

- `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1-ssh`
- Digest: `sha256:7d4fe3ab9198ce36beb8d8b891a9676bdcedbae428105c71bc60a37dc9b2be50`

Command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg-runtime@sha256:7d4fe3ab9198ce36beb8d8b891a9676bdcedbae428105c71bc60a37dc9b2be50 `
  s3://3dgen-runs/runs/triposg/wave1/20260708T174136Z `
  --name 3dgen-triposg-wave1-ssh-20260708T174136Z `
  --min-balance-usd 12 `
  --gpu-type-id "NVIDIA GeForce RTX 4090" `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id wnqijpazd5 `
  --data-center-id EU-RO-1 `
  --startup-timeout-min 25 `
  --allowed-cuda-version 13.0 `
  --allowed-cuda-version 12.9 `
  --allowed-cuda-version 12.8
```

Observed:

- Pod id: `jlnk4q5rjjh3m3`
- Cost reported by RunPod: `$0.69/hr`
- GPU: RTX 4090 x1
- Data center: `EU-RO-1`
- Network volume: `wnqijpazd5`
- R2 prefix: `runs/triposg/wave1/20260708T174136Z/`
- SSH became reachable at `213.173.109.42:13674`, confirming the image and start command fixed the prior SSH daemon gap.
- SSH inspection showed the runner active with GPU utilization at 100%.
- Before the pod disappeared, `/work/output` contained 23 task directories and 22 `meta.json` files; the active task was `anime-ramen-bowl`.
- The pod then disappeared from `GET /pods` and `runpod-pods`; active pods returned to `[]`.
- R2 object count under the run prefix stayed `0` because the final upload sweep never ran.

Conclusion: the runtime image and SSH readiness path are now viable, and the model runner can make real progress on the staged EU-RO-1 volume. Final-only upload is not robust enough for RunPod pod disappearance or host interruption. The next retry uses task-level incremental R2 upload so completed tasks are preserved as soon as they finish.

## SSH + Incremental Runtime Image

Documented at 2026-07-09T03:18Z after rebuilding and pushing the corrected runner.

- Image tag: `ghcr.io/hitsuki-ban/3dgen-triposg-runtime:2026-07-cloud-wave1-ssh-incremental`
- Digest: `sha256:5a3088fa4038648d0f5b19200c03a5ec45fb206947503ac24dafb6443a6403f8`
- Registry inspect confirmed the tag points at that digest.
- The image includes SSH daemon support plus the TripoSG runner change that uploads each task directory to R2 under `<run-prefix>/<task-id>/`.
- Docker daemon was cleaned afterward: `docker system df` returned `0` images, `0` containers, `0` build cache. The temporary F: buildx cache directory was deleted after the push.

Next retry command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg-runtime@sha256:5a3088fa4038648d0f5b19200c03a5ec45fb206947503ac24dafb6443a6403f8 `
  s3://3dgen-runs/runs/triposg/wave1/<timestamp> `
  --name 3dgen-triposg-wave1-ssh-incremental-<timestamp> `
  --min-balance-usd 12 `
  --gpu-type-id "NVIDIA GeForce RTX 4090" `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des `
  --network-volume-id wnqijpazd5 `
  --data-center-id EU-RO-1 `
  --startup-timeout-min 25 `
  --allowed-cuda-version 13.0 `
  --allowed-cuda-version 12.9 `
  --allowed-cuda-version 12.8
```

## Log Access Notes

- `runpodctl` v2.6.1 was installed locally under gitignored `.docker-build/tools/runpodctl-2.6.1`; checksum matched the official release checksum.
- `runpodctl pod list` works with `RUNPOD_API_KEY`, but `runpodctl pod get` prints full pod env values, so do not use raw output in reports.
- RunPod REST OpenAPI (`https://rest.runpod.io/v1/openapi.json`, checked 2026-07-08) has 23 paths and no `log`, `event`, `console`, or `terminal` path.
- GraphQL introspection is disabled on `https://api.runpod.io/graphql`, so hidden log fields cannot be enumerated.
- Common guessed REST log endpoints such as `/v1/pods/<id>/logs` returned route schema errors.
- Practical log path today: open `https://console.runpod.io/pods`, click the pod row, open the `Logs` tab, then switch between `Container` and `System` or use the `Download logs` button.

## Default Cloud Launch Values

- `MIN_BALANCE_USD`: code default is `5.0`, but Issue #25 GO instruction requires launching with `--min-balance-usd 12`
- `MAX_RUNTIME_MIN`: `90`
- `gpuTypeIds`: `NVIDIA GeForce RTX 5090`, then `NVIDIA GeForce RTX 4090`
- `gpuTypePriority`: `custom`
- `dataCenterIds`: current retry volume is in `EU-RO-1`
- `dataCenterPriority`: `custom`
- `allowedCudaVersions`: code default is `12.8`; the successful pod allocation used `13.0`, `12.9`, `12.8` to avoid over-filtering available 5090 machines
- `containerRegistryAuthId`: `cmrc1l2gc00847uotrnjn2des`
- `networkVolumeId`: `wnqijpazd5`
- `startupTimeoutMin`: required per launch, launcher-side pre-container watchdog
- `cloudType`: `SECURE`
- `computeType`: `GPU`
- `interruptible`: `false`

## Follow-up Before Full 25-Task Runs

1. Retry TripoSG with `ghcr.io/hitsuki-ban/3dgen-triposg-runtime@sha256:5a3088fa4038648d0f5b19200c03a5ec45fb206947503ac24dafb6443a6403f8` on EU-RO-1 / `wnqijpazd5` using private registry auth.
2. Monitor both SSH and R2. The first completed task should create objects under `runs/triposg/wave1/<timestamp>/<task-id>/` before the full run ends.
3. If the rebuilt private runtime stalls before SSH readiness, choose the next registry/bootstrap isolation path: make the weight-free package public after explicit approval, or run a tiny diagnostic image against the same data center/volume.
4. After a successful TripoSG run, validate every task with `output-validate`, sync artifacts into `outputs/site-data/triposg/<task-id>/`, then run PartCrafter with the same volume and a matching weight-free runtime package.

## Source Checks

- RunPod Pods API: https://docs.runpod.io/api-reference/pods/POST/pods
- RunPod Network Volumes docs: https://docs.runpod.io/storage/network-volumes
- RunPod Pod logs docs: https://docs.runpod.io/pods/references/pod-logs
- RunPod CLI release: https://github.com/Run-Pod/runpodctl/releases/tag/v2.6.1
- GitHub package access control and visibility: https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility
- Cloudflare R2 bucket and S3 credential docs: https://developers.cloudflare.com/r2/

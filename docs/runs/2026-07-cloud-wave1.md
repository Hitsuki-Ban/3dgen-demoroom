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

## GHCR Images

| Model | Image | Digest | Package visibility |
| --- | --- | --- | --- |
| TripoSG | `ghcr.io/hitsuki-ban/3dgen-triposg:2026-07-cloud-wave1` | `sha256:20683da63af15a45e64d6f4dfcb2c92763b6bc33f71bb046c0c852c2aae7e6b9` | private |
| PartCrafter | `ghcr.io/hitsuki-ban/3dgen-partcrafter:2026-07-cloud-wave1` | `sha256:b84791ae147f43dc5556bb8d853b2b16f311c657a96fecdff6f1706bd3b2df9b` | private |

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

## TripoSG Launch Attempt

Command shape:

```powershell
uv run bench-harness runpod-launch triposg `
  ghcr.io/hitsuki-ban/3dgen-triposg@sha256:20683da63af15a45e64d6f4dfcb2c92763b6bc33f71bb046c0c852c2aae7e6b9 `
  s3://3dgen-runs/runs/triposg/rtx-5090/20260708T125024Z `
  --name 3dgen-triposg-wave1-20260708T125024Z `
  --min-balance-usd 12 `
  --container-registry-auth-id cmrc1l2gc00847uotrnjn2des
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

See also: [RunPod large artifact handling: Codex notes](../research/runpod-large-artifacts-codex.md). The recommended path is to switch from baked-weight GHCR layers to runtime-only images plus a pre-populated RunPod network volume.

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
- `allowedCudaVersions`: `12.8`
- `containerRegistryAuthId`: `cmrc1l2gc00847uotrnjn2des`
- `cloudType`: `SECURE`
- `computeType`: `GPU`
- `interruptible`: `false`

## Follow-up Before Full 25-Task Runs

1. Shrink or restructure TripoSG/PartCrafter cloud images before another full run. The first observed pull was dominated by an 8.073GB layer and was not compatible with the intended launch guardrail.
2. Prefer runtime-only images plus a RunPod network volume pre-populated with pinned model revisions. Avoid another full launch with baked-weight image layers.
3. Add launcher support for `networkVolumeId` / volume mount path and runner support for env-configured weight paths.
4. Add a launcher-side wall-clock watchdog for the pre-container phase, because `MAX_RUNTIME_MIN` only runs inside the container and cannot stop a pod stuck while pulling an image.
5. Launch one model at a time with `--container-registry-auth-id cmrc1l2gc00847uotrnjn2des`, verify `bench-harness runpod-pods` after completion, and sync uploaded artifacts into `outputs/site-data/<model-id>/<task-id>/`.

## Source Checks

- RunPod Pods API: https://docs.runpod.io/api-reference/pods/POST/pods
- RunPod Network Volumes docs: https://docs.runpod.io/storage/network-volumes
- RunPod Pod logs docs: https://docs.runpod.io/pods/references/pod-logs
- RunPod CLI release: https://github.com/Run-Pod/runpodctl/releases/tag/v2.6.1
- Cloudflare R2 bucket and S3 credential docs: https://developers.cloudflare.com/r2/

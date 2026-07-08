# 2026-07 Cloud Wave 1

Checked: 2026-07-08
Issue: #25

## Status

Implemented the local code needed for the first RunPod/R2 cloud wave and pushed the first two cloud images to GHCR. GPU jobs have not launched yet.

- RunPod API key is present as a GitHub secret: `RUNPOD_API_KEY`.
- R2 is enabled. Cloudflare API created bucket `3dgen-runs` on 2026-07-08T04:35:35Z with location `APAC`, storage class `Standard`, jurisdiction `default`.
- Cloudflare R2 object API probe passed: wrote, listed, and deleted `_codex-api-probe.txt`.
- R2 S3-compatible upload probe passed through `bench-harness upload-s3`, then `_codex-s3-probe/probe.txt` was deleted through Cloudflare REST API.
- GitHub secrets are set: `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Current Cloudflare connector cannot create account-owned API tokens; permission group lookup returned `9109: Unauthorized to access requested resource`.
- No RunPod pods were launched in this pass, so there are no cloud artifacts or pod cleanup records yet.
- Local execution environment does not currently expose `RUNPOD_API_KEY`, `R2_ENDPOINT`, `R2_ACCESS_KEY_ID`, or `R2_SECRET_ACCESS_KEY`; the values are present as GitHub secrets but cannot be read back by the local CLI.
- GHCR packages were created as private by default. RunPod private registry auth has been provisioned as `cmrc1l2gc00847uotrnjn2des`.

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

1. Provide local launch credentials (`RUNPOD_API_KEY` plus R2 S3 env vars) or run the launcher from a GitHub Actions path that can consume the existing repository secrets.
2. Launch one model at a time with `--container-registry-auth-id cmrc1l2gc00847uotrnjn2des`, verify `bench-harness runpod-pods` after completion, and sync uploaded artifacts into `outputs/site-data/<model-id>/<task-id>/`.

## Source Checks

- RunPod Pods API: https://docs.runpod.io/api-reference/pods/POST/pods
- Cloudflare R2 bucket and S3 credential docs: https://developers.cloudflare.com/r2/

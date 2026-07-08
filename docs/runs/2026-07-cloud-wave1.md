# 2026-07 Cloud Wave 1

Checked: 2026-07-08
Issue: #25

## Status

Implemented the local code needed for the first RunPod/R2 cloud wave, but did not launch GPU jobs yet.

- RunPod API key is present as a GitHub secret: `RUNPOD_API_KEY`.
- R2 is enabled. Cloudflare API created bucket `3dgen-runs` on 2026-07-08T04:35:35Z with location `APAC`, storage class `Standard`, jurisdiction `default`.
- Cloudflare R2 object API probe passed: wrote, listed, and deleted `_codex-api-probe.txt`.
- GitHub secret `R2_ENDPOINT` is set to the account S3-compatible endpoint.
- GitHub secrets still missing: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
- Current Cloudflare connector cannot create account-owned API tokens; permission group lookup returned `9109: Unauthorized to access requested resource`.
- No RunPod pods were launched in this pass, so there are no cloud artifacts or pod cleanup records yet.

## Implemented

- `bench-harness upload-s3` uploads a run directory to `s3://<bucket>/<prefix>` through Cloudflare R2 S3-compatible credentials.
- `bench-harness runpod-launch` builds a RunPod Pods API payload for TripoSG or PartCrafter, checks `clientBalance`, then creates an on-demand pod.
- `bench-harness runpod-pods` and `bench-harness runpod-terminate` provide the GET /pods confirmation and cleanup path for the later GPU pass.
- TripoSG and PartCrafter Docker images now build from the repository root context and include `bench/src` plus `tasks/` so pod startup can run all 25 tasks and upload results.
- TripoSG and PartCrafter runners retry each failed task once and write `failure.json` after the retry fails, allowing the remaining 25-task batch to continue.
- Root `.dockerignore` excludes `.git`, `.worktrees`, `.docker-build`, `outputs`, and local Python/Node build directories from model image contexts.

## Default Cloud Launch Values

- `MIN_BALANCE_USD`: `5.0`, overridable with `RUNPOD_MIN_BALANCE_USD` or `--min-balance-usd`
- `MAX_RUNTIME_MIN`: `90`
- `gpuTypeIds`: `NVIDIA GeForce RTX 5090`, then `NVIDIA GeForce RTX 4090`
- `gpuTypePriority`: `custom`
- `allowedCudaVersions`: `12.8`
- `cloudType`: `SECURE`
- `computeType`: `GPU`
- `interruptible`: `false`

## Follow-up Before Full 25-Task Runs

1. Create R2 S3 credentials scoped to bucket `3dgen-runs` with Object Read & Write permission.
2. Set GitHub secrets: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
3. Push current TripoSG and PartCrafter images to GHCR and record image digests.
4. Launch one model at a time, verify `bench-harness runpod-pods` after completion, and sync uploaded artifacts into `outputs/site-data/<model-id>/<task-id>/`.

## Source Checks

- RunPod Pods API: https://docs.runpod.io/api-reference/pods/POST/pods
- Cloudflare R2 bucket and S3 credential docs: https://developers.cloudflare.com/r2/

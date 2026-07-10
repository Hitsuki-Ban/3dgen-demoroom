# Stable Fast 3D Runner

This runtime-only runner implements the benchmark container contract for Stable Fast 3D.

Pinned sources:

- Code: `Stability-AI/stable-fast-3d` at `ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2`
- Weights: `stabilityai/stable-fast-3d` at `f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778`
- DINOv2 Large cache: `facebook/dinov2-large` at `47b73eefe95e8d44ec3623f8890bd894b6ea2d6c`
- OpenCLIP cache: `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` at `1a25a446712ba5ee05982a381eed697ef9b435cf`

The benchmark keeps the official defaults: background removal, foreground ratio `0.85`, texture resolution `1024`, no remeshing, and no vertex-count reduction. The seed is recorded and applied to torch even though Stable Fast 3D is a feed-forward reconstruction model.

Weights plus the DINOv2 and OpenCLIP caches must be staged on the RunPod network volume. Runtime Hub access is disabled. Build and push with:

```powershell
.\scripts\docker-build-model.ps1 sf3d -Tag ghcr.io/hitsuki-ban/3dgen-sf3d-runtime:2026-07-cloud-wave2-v1 -Push
```

The Stability AI Community License requires attribution when the model or a derivative product is distributed. Each task output therefore includes the code license, weights license, and the required notice in `LICENSES.txt`.

# TRELLIS.2 Runner

Runtime-only image-to-3D runner for `microsoft/TRELLIS.2-4B`.

Checked on 2026-07-09:

- Code: `https://github.com/microsoft/TRELLIS.2` at `75fbf0183001ed9876c8dbb35de6b68552ee08bd`
- Weights: `microsoft/TRELLIS.2-4B` at `af44b45f2e35a493886929c6d786e563ec68364d`
- Hidden runtime dependencies: `facebook/dinov3-vitl16-pretrain-lvd1689m`, `briaai/RMBG-2.0`, and the sparse structure decoder files from `microsoft/TRELLIS-image-large`

The runner expects a RunPod network volume mounted at `/workspace` with:

- `/workspace/weights/TRELLIS.2-4B`
- Hugging Face cache entries under `/workspace/hf` for the gated DINOv3/RMBG-2.0 dependencies
- Torch hub/cache entries under `/workspace/torch` if prewarming is needed

`TRELLIS2_WEIGHTS_PATH` is required and defaults to `/workspace/weights/TRELLIS.2-4B` in the container. The runner does not download weights at runtime; missing files fail fast.

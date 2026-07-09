# Direct3D-S2 Runner

Runtime-only geometry runner for `wushuang98/Direct3D-S2`, using the official `direct3d-s2-v-1-1` checkpoint directory at 1024 SDF resolution.

Checked on 2026-07-09:

- Code: `https://github.com/DreamTechAI/Direct3D-S2` at `a1cf235b2881cff04a91900060a9546b40e7ee5d`
- Weights: `wushuang98/Direct3D-S2` at `8b04a8eddb7a56a0f4e89fe5f5b840c7d5610c00`
- Official VRAM guidance: 512 resolution needs about 10GB; 1024 resolution needs about 24GB. The wave 2 protocol uses 1024 and records OOM as a model failure instead of dropping to 512.

The runner expects:

- `/workspace/weights/Direct3D-S2/direct3d-s2-v-1-1/`
- `/workspace/hf` for Hugging Face cache dependencies such as BiRefNet
- `/workspace/torch` for torch hub dependencies such as DINOv2

Outputs are geometry-only GLB files. The raw OBJ is preserved under `raw/direct3d-s2/output.obj` for audit.

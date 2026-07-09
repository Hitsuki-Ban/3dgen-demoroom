# 3DTopia-XL Runner

This runner implements the benchmark container contract for 3DTopia-XL single-image inference.

## Build

```powershell
.\scripts\docker-build-model.ps1 3dtopia-xl
```

The Dockerfile pins:

- Code: `3DTopia/3DTopia-XL` at `4017e5bfbaab7f73632b47311a92a434abb9d2fc`
- Weights: `FrozenBurning/3DTopia-XL` at `8a348b850d36d6354a26917d531eb8f2a5633515`
- `nvdiffrast` at `253ac4fcea7de5f396371124af597e6cc957bfae`
- `cubvh` at `757b913bfbf19ed65e3a379d159391a8e29efa0f`
- Base: `nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04`
- Python: `3.9.23` in `/opt/venv`, matching the official `python=3.9` environment
- Torch: `2.1.2` cu118

The container is runtime-only with respect to model weights. The RunPod network volume must provide:

- `/workspace/weights/3DTopia-XL/model_sview_dit_fp16.pt`
- `/workspace/weights/3DTopia-XL/model_vae_fp16.pt`
- `/workspace/weights/3DTopia-XL/README.md`
- `/workspace/torch` with the DINOv2 `dinov2_vitb14_reg4_pretrain.pth` torch cache
- `/workspace/weights/rembg` with the U2NET rembg cache

The runner calls 3DTopia-XL's official `inference.py` with the repository `configs/inference_dit.yml`, overriding only per-task paths and seed. It preserves the official single-view defaults: `ddim=25`, `cfg=6`, `precision=fp16`, `export_glb=true`, `mc_resolution=256`, and `decimate=100000`.

Expected output per task:

- `output.glb`
- `meta.json`
- `LICENSES.txt`
- `raw/3dtopia-xl/output.glb`
- `raw/3dtopia-xl/inference_overrides.json`
- `raw/3dtopia-xl/runs/...` official intermediate outputs

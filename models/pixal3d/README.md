# Pixal3D runtime runner

This runner executes the official Pixal3D image-to-GLB path in standard mode with explicit `1536` resolution.

It intentionally does not enable low-VRAM mode. If the standard protocol OOMs on RTX 5090, the benchmark records `failure.json` for that task instead of switching to `1024`.

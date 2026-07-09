# Step1X-3D runtime runner

This runner executes the official base geometry model (`Step1X-3D-Geometry-1300m`) followed by the official texture pipeline (`Step1X-3D-Texture`).

Weights are staged on the RunPod network volume at `STEP1X_3D_WEIGHTS_PATH`; the image does not download weights at runtime.

FROM ghcr.io/hitsuki-ban/3dgen-natten-wheel@sha256:bcbadc4205c6c80282d8360a3eeb4eeeae0f9d6c4b5f17f91cccff7281bdafb4 AS natten-wheel

FROM ghcr.io/hitsuki-ban/3dgen-trellis2-runtime@sha256:680f4189db4fa6d02c6cda75512fe98faacd9c9dabaa2e08a0afe3aea0b110ed

ARG PIXAL3D_COMMIT=cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af
ARG PIXAL3D_WEIGHTS_REVISION=0b31f9160aa400719af409098bff7936a932f726
ARG MOGE_COMMIT=07444410f1e33f402353b99d6ccd26bd31e469e8
ARG NATTEN_WHEEL_SHA256=a0bccfb8da194fc909eddaf77573b6a12303839a4bc70964240a7b10546631c0

ENV HF_HOME=/workspace/hf \
    TORCH_HOME=/workspace/torch \
    TORCH_CUDA_ARCH_LIST="8.9;12.0" \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/Pixal3D \
    PIXAL3D_WEIGHTS_PATH=/workspace/weights/Pixal3D \
    ATTN_BACKEND=flash_attn \
    SPARSE_ATTN_BACKEND=flash_attn

RUN git clone https://github.com/TencentARC/Pixal3D.git /opt/Pixal3D \
    && git -C /opt/Pixal3D checkout ${PIXAL3D_COMMIT} \
    && test "$(git -C /opt/Pixal3D rev-parse HEAD)" = "${PIXAL3D_COMMIT}"

COPY --from=natten-wheel /natten-0.21.0-cp310-cp310-linux_x86_64.whl /tmp/natten-0.21.0-cp310-cp310-linux_x86_64.whl

RUN uv pip install --system \
        accelerate==1.13.0 \
        diffusers==0.37.1 \
        easydict==1.13 \
        imageio==2.37.2 \
        imageio-ffmpeg==0.6.0 \
        kornia==0.8.2 \
        opencv-python-headless==4.12.0.88 \
        pillow==12.0.0 \
        plyfile==1.1.3 \
        timm==1.0.22 \
        tqdm==4.67.1 \
        trimesh==4.10.1 \
        zstandard==0.25.0 \
        "git+https://github.com/microsoft/MoGe.git@${MOGE_COMMIT}" \
    && uv pip uninstall --system opencv-python \
    && uv pip install --system --reinstall opencv-python-headless==4.12.0.88 \
    && printf '%s  %s\n' "${NATTEN_WHEEL_SHA256}" /tmp/natten-0.21.0-cp310-cp310-linux_x86_64.whl | sha256sum -c - \
    && uv pip install --system /tmp/natten-0.21.0-cp310-cp310-linux_x86_64.whl \
    && rm /tmp/natten-0.21.0-cp310-cp310-linux_x86_64.whl \
    && uv pip install --system https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl

RUN python3 - <<'PY'
from importlib.metadata import version

import cv2
from moge.model.v2 import MoGeModel

assert cv2.__version__ == "4.12.0"
assert version("moge") == "2.0.0"
assert version("natten") == "0.21.0"
assert MoGeModel.__name__ == "MoGeModel"
PY

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/pixal3d/runner.py /opt/3dgen-runner/pixal3d_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "-m", "bench_harness.container_entrypoint", "--model-id", "pixal3d", "--runner-path", "/opt/3dgen-runner/pixal3d_runner.py"]

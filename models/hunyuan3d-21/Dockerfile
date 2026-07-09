FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ARG HUNYUAN3D_21_COMMIT=82920d643c0dc2f7bfd7255f45f62d386edfe60c
ARG HUNYUAN3D_21_WEIGHTS_REVISION=0b94677654c57bb9a6b6845cd7b704ccf551d327
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/Hunyuan3D-2.1:/opt/Hunyuan3D-2.1/hy3dshape:/opt/Hunyuan3D-2.1/hy3dpaint \
    HUNYUAN3D_21_WEIGHTS_PATH=/workspace/weights/Hunyuan3D-2.1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    ATTN_BACKEND=xformers \
    TORCH_CUDA_ARCH_LIST="8.0;8.9" \
    CUDA_HOME=/usr/local/cuda \
    FORCE_CUDA=1 \
    CPATH=/usr/local/cuda/include \
    LIBRARY_PATH=/usr/local/cuda/lib64

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        git \
        libegl1 \
        libglib2.0-0 \
        libgl1 \
        libgl1-mesa-dev \
        libjpeg-dev \
        make \
        ninja-build \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/tencent-hunyuan/hunyuan3d-2.1.git /opt/Hunyuan3D-2.1 \
    && cd /opt/Hunyuan3D-2.1 \
    && git checkout ${HUNYUAN3D_21_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${HUNYUAN3D_21_COMMIT}" \
    && sed -i 's#^bpy==4\.0$#bpy @ https://download.blender.org/pypi/bpy/bpy-4.0.0-cp310-cp310-manylinux_2_28_x86_64.whl#' requirements.txt \
    && grep -Fx 'bpy @ https://download.blender.org/pypi/bpy/bpy-4.0.0-cp310-cp310-manylinux_2_28_x86_64.whl' requirements.txt \
    && sed -i 's#`python -m pybind11 --includes`#`python3 -m pybind11 --includes`#' hy3dpaint/DifferentiableRenderer/compile_mesh_painter.sh \
    && grep -F '`python3 -m pybind11 --includes`' hy3dpaint/DifferentiableRenderer/compile_mesh_painter.sh

RUN uv pip install --system "setuptools<81" wheel \
    && uv pip install --system \
        torch==2.5.1 \
        torchvision==0.20.1 \
        torchaudio==2.5.1 \
        --index-url https://download.pytorch.org/whl/cu124 \
    && uv pip install --system xformers==0.0.28.post3 --index-url https://download.pytorch.org/whl/cu124 \
    && printf '%s\n' \
        'torch==2.5.1' \
        'torchvision==0.20.1' \
        'torchaudio==2.5.1' \
        'xformers==0.0.28.post3' \
        > /tmp/hunyuan3d-21-requirements-constraints.txt \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation \
        --index-strategy unsafe-best-match \
        --constraint /tmp/hunyuan3d-21-requirements-constraints.txt \
        -r /opt/Hunyuan3D-2.1/requirements.txt

RUN uv pip install --system --no-build-isolation /opt/Hunyuan3D-2.1/hy3dpaint/custom_rasterizer \
    && cd /opt/Hunyuan3D-2.1/hy3dpaint/DifferentiableRenderer \
    && bash compile_mesh_painter.sh

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/hunyuan3d-21/runner.py /opt/3dgen-runner/hunyuan3d_21_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/hunyuan3d_21_runner.py"]

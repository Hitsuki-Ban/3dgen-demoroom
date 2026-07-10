FROM nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04

ARG TRELLIS_COMMIT=442aa1e1afb9014e80681d3bf604e8d728a86ee7
ARG TRELLIS_WEIGHTS_REVISION=25e0d31ffbebe4b5a97464dd851910efc3002d96
ARG UTILS3D_COMMIT=9a4eb15e4021b67b12c460c7057d642626897ec8
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner \
    TRELLIS1_WEIGHTS_PATH=/workspace/weights/TRELLIS-image-large \
    ATTN_BACKEND=xformers \
    SPCONV_ALGO=native \
    TORCH_CUDA_ARCH_LIST="8.9" \
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
        libjpeg-dev \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone --recurse-submodules https://github.com/microsoft/TRELLIS.git /opt/TRELLIS \
    && cd /opt/TRELLIS \
    && git checkout ${TRELLIS_COMMIT} \
    && git submodule update --init --recursive \
    && test "$(git rev-parse HEAD)" = "${TRELLIS_COMMIT}"

RUN uv pip install --system \
        torch==2.4.0 \
        torchvision==0.19.0 \
        --index-url https://download.pytorch.org/whl/cu121 \
    && uv pip install --system \
        boto3 \
        cmake \
        easydict \
        igraph \
        imageio \
        imageio-ffmpeg \
        ninja \
        onnxruntime \
        open3d \
        opencv-python-headless \
        pillow \
        pybind11 \
        pymeshfix \
        pyvista \
        rembg \
        scikit-build-core \
        scipy \
        tqdm \
        transformers \
        trimesh \
        xatlas \
    && uv pip install --system xformers==0.0.27.post2 --index-url https://download.pytorch.org/whl/cu121 \
    && uv pip install --system "git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_COMMIT}" \
    && uv pip install --system kaolin -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html

RUN mkdir -p /tmp/extensions \
    && git clone --recurse-submodules https://github.com/JeffreyXiang/diffoctreerast.git /tmp/extensions/diffoctreerast \
    && uv pip install --system --no-build-isolation /tmp/extensions/diffoctreerast \
    && git clone https://github.com/autonomousvision/mip-splatting.git /tmp/extensions/mip-splatting \
    && uv pip install --system --no-build-isolation /tmp/extensions/mip-splatting/submodules/diff-gaussian-rasterization \
    && git clone https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast \
    && uv pip install --system --no-build-isolation /tmp/extensions/nvdiffrast \
    && uv pip install --system spconv-cu120 \
    && rm -rf /tmp/extensions

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/trellis1/runner.py /opt/3dgen-runner/trellis1_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/trellis1_runner.py"]

FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG SF3D_COMMIT=ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2
ARG SF3D_WEIGHTS_REVISION=f0c9a8ffd62cb1bbc8a7a53c9f87a0be1b6be778
ARG DINOV2_LARGE_REVISION=47b73eefe95e8d44ec3623f8890bd894b6ea2d6c
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner \
    SF3D_WEIGHTS_PATH=/workspace/weights/stable-fast-3d \
    TORCH_CUDA_ARCH_LIST="8.9;12.0" \
    CUDA_HOME=/usr/local/cuda \
    FORCE_CUDA=1 \
    USE_CUDA=1 \
    USE_NATIVE_ARCH=0 \
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
        libgomp1 \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/Stability-AI/stable-fast-3d.git /opt/stable-fast-3d \
    && cd /opt/stable-fast-3d \
    && git checkout ${SF3D_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${SF3D_COMMIT}"

RUN uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system boto3 cmake ninja pybind11 scikit-build-core \
    && cd /opt/stable-fast-3d \
    && MAX_JOBS=2 uv pip install --system --no-build-isolation -r requirements.txt

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/sf3d/runner.py /opt/3dgen-runner/sf3d_runner.py
COPY models/sf3d/NOTICE.txt /opt/3dgen-runner/sf3d_NOTICE.txt

WORKDIR /work
ENTRYPOINT ["python3", "-m", "bench_harness.container_entrypoint", "--model-id", "sf3d", "--runner-path", "/opt/3dgen-runner/sf3d_runner.py"]

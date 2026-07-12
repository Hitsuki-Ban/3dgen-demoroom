FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG STEP1X_3D_COMMIT=cb5ac944709c6c913109070c7b90c3447f57f3d4
ARG STEP1X_3D_WEIGHTS_REVISION=bf7084495b3a72222f36549b7942948aa4d9daa7
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/Step1X-3D \
    STEP1X_3D_WEIGHTS_PATH=/workspace/weights/Step1X-3D \
    TORCH_CUDA_ARCH_LIST="8.9;12.0" \
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
        make \
        ninja-build \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/stepfun-ai/Step1X-3D.git /opt/Step1X-3D \
    && cd /opt/Step1X-3D \
    && git checkout ${STEP1X_3D_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${STEP1X_3D_COMMIT}"

RUN uv pip install --system "setuptools<81" wheel \
    && uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        torchaudio==2.7.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system torch-cluster -f https://data.pyg.org/whl/torch-2.7.0+cu128.html

RUN MAX_JOBS=1 uv pip install --system --no-build-isolation -r /opt/Step1X-3D/requirements.txt

RUN uv pip install --system boto3 \
    && uv pip install --system --no-build-isolation /opt/Step1X-3D/step1x3d_texture/custom_rasterizer \
    && uv pip install --system --no-build-isolation /opt/Step1X-3D/step1x3d_texture/differentiable_renderer

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/step1x-3d/runner.py /opt/3dgen-runner/step1x_3d_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "-m", "bench_harness.container_entrypoint", "--model-id", "step1x-3d", "--runner-path", "/opt/3dgen-runner/step1x_3d_runner.py"]

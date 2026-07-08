FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG PARTCRAFTER_COMMIT=3d773bf02fad51c7ab31a5615573fec93b287b30
ARG PARTCRAFTER_WEIGHTS_REVISION=69a0ffc1dad5e48e7e5ed91c0609f2b1276eb31f
ARG RMBG_WEIGHTS_REVISION=2ceba5a5efaec153162aedea169f76caf9b46cf8
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    TORCH_CUDA_ARCH_LIST="8.9;12.0" \
    CUDA_HOME=/usr/local/cuda \
    CPATH=/usr/local/cuda/include \
    LIBRARY_PATH=/usr/local/cuda/lib64 \
    PATH="/opt/venv/bin:${PATH}"

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
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh \
    && uv python install 3.11.13 \
    && uv venv --python 3.11.13 /opt/venv

RUN git clone https://github.com/wgsxm/PartCrafter.git /opt/PartCrafter \
    && cd /opt/PartCrafter \
    && git checkout ${PARTCRAFTER_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${PARTCRAFTER_COMMIT}"

RUN uv pip install --python /opt/venv/bin/python \
        torch==2.7.0 \
        torchvision==0.22.0 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --python /opt/venv/bin/python \
        torch-cluster \
        -f https://data.pyg.org/whl/torch-2.7.0+cu128.html \
    && uv pip install --python /opt/venv/bin/python \
        accelerate \
        scikit-learn \
        gpustat \
        nvitop \
        diffusers \
        transformers \
        einops \
        huggingface_hub \
        opencv-python \
        trimesh \
        omegaconf \
        scikit-image \
        numpy==1.26.4 \
        peft \
        jaxtyping \
        typeguard \
        matplotlib \
        imageio-ffmpeg \
        colormaps

RUN PARTCRAFTER_WEIGHTS_REVISION="${PARTCRAFTER_WEIGHTS_REVISION}" \
    RMBG_WEIGHTS_REVISION="${RMBG_WEIGHTS_REVISION}" \
    python3 - <<'PY'
import os

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="wgsxm/PartCrafter",
    revision=os.environ["PARTCRAFTER_WEIGHTS_REVISION"],
    local_dir="/opt/weights/PartCrafter",
)
snapshot_download(
    repo_id="briaai/RMBG-1.4",
    revision=os.environ["RMBG_WEIGHTS_REVISION"],
    local_dir="/opt/weights/RMBG-1.4",
)
PY

COPY runner.py /opt/3dgen-runner/partcrafter_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/partcrafter_runner.py"]

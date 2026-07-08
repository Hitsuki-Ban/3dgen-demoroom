FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG TRIPOSG_COMMIT=fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c
ARG TRIPOSG_WEIGHTS_REVISION=2c1c516d22d58db486a058d98d31bb6177344e06
ARG RMBG_WEIGHTS_REVISION=2ceba5a5efaec153162aedea169f76caf9b46cf8
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PYTHONPATH=/opt/bench/src \
    TRIPOSG_WEIGHTS_PATH=/workspace/weights/TripoSG \
    RMBG_WEIGHTS_PATH=/workspace/weights/RMBG-1.4 \
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
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/VAST-AI-Research/TripoSG.git /opt/TripoSG \
    && cd /opt/TripoSG \
    && git checkout ${TRIPOSG_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${TRIPOSG_COMMIT}"

RUN uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system boto3 scikit-build-core cmake ninja pybind11 \
    && uv pip install --system --no-build-isolation-package diso -r /opt/TripoSG/requirements.txt

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/triposg/runner.py /opt/3dgen-runner/triposg_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/triposg_runner.py"]

FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG TRIPOSR_COMMIT=107cefdc244c39106fa830359024f6a2f1c78871
ARG TRIPOSR_WEIGHTS_REVISION=5b521936b01fbe1890f6f9baed0254ab6351c04a
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache \
    PYTHONPATH=/opt/bench/src \
    TORCH_CUDA_ARCH_LIST="8.9;12.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        build-essential \
        git \
        libegl1 \
        libglib2.0-0 \
        libgl1 \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/VAST-AI-Research/TripoSR.git /opt/TripoSR \
    && cd /opt/TripoSR \
    && git checkout ${TRIPOSR_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${TRIPOSR_COMMIT}"

RUN uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system scikit-build-core cmake ninja pybind11 \
    && export CMAKE_PREFIX_PATH="$(python3 -c 'import torch; print(torch.utils.cmake_prefix_path)')" \
    && uv pip install --system --no-build-isolation-package torchmcubes -r /opt/TripoSR/requirements.txt \
    && uv pip install --system onnxruntime boto3

RUN python3 - <<'PY'
import rembg

rembg.new_session()
PY

RUN TRIPOSR_WEIGHTS_REVISION="${TRIPOSR_WEIGHTS_REVISION}" python3 - <<'PY'
import os

from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="stabilityai/TripoSR",
    revision=os.environ["TRIPOSR_WEIGHTS_REVISION"],
    local_dir="/opt/weights/TripoSR",
    allow_patterns=["config.yaml", "model.ckpt"],
)
PY

COPY bench/src /opt/bench/src
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/triposr/runner.py /opt/3dgen-runner/triposr_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "-m", "bench_harness.container_entrypoint", "--model-id", "triposr", "--runner-path", "/opt/3dgen-runner/triposr_runner.py"]

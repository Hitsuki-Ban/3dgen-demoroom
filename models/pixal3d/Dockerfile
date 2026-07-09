FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG PIXAL3D_COMMIT=cdbb2bbffbf4e6f298b5f2af3d1d76a8d823d2af
ARG PIXAL3D_WEIGHTS_REVISION=0b31f9160aa400719af409098bff7936a932f726
ARG TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
ARG NVDIFFRAST_REF=v0.4.0
ARG NVDIFFREC_REF=renderutils
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/Pixal3D \
    PIXAL3D_WEIGHTS_PATH=/workspace/weights/Pixal3D \
    OPENCV_IO_ENABLE_OPENEXR=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    ATTN_BACKEND=flash_attn \
    SPARSE_ATTN_BACKEND=flash_attn \
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
        libjpeg-dev \
        make \
        ninja-build \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/TencentARC/Pixal3D.git /opt/Pixal3D \
    && cd /opt/Pixal3D \
    && git checkout ${PIXAL3D_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${PIXAL3D_COMMIT}"

RUN git clone --recurse-submodules https://github.com/microsoft/TRELLIS.2.git /tmp/TRELLIS.2 \
    && cd /tmp/TRELLIS.2 \
    && git checkout ${TRELLIS2_COMMIT} \
    && git submodule update --init --recursive \
    && test "$(git rev-parse HEAD)" = "${TRELLIS2_COMMIT}"

RUN uv pip install --system "setuptools<81" wheel \
    && uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system \
        boto3 \
        cmake \
        numpy==1.26.4 \
        scikit-build-core \
    && uv pip install --system -r /opt/Pixal3D/requirements.txt \
    && NATTEN_CUDA_ARCH="8.9;12.0" NATTEN_N_WORKERS=1 uv pip install --system natten==0.21.0 --no-build-isolation \
    && MAX_JOBS=1 uv pip install --system flash-attn --no-build-isolation \
    && uv pip install --system https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl

RUN mkdir -p /tmp/extensions \
    && git clone -b ${NVDIFFRAST_REF} https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/extensions/nvdiffrast \
    && git clone -b ${NVDIFFREC_REF} https://github.com/JeffreyXiang/nvdiffrec.git /tmp/extensions/nvdiffrec \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/extensions/nvdiffrec \
    && git clone --recurse-submodules https://github.com/JeffreyXiang/CuMesh.git /tmp/extensions/CuMesh \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/extensions/CuMesh \
    && git clone --recurse-submodules https://github.com/JeffreyXiang/FlexGEMM.git /tmp/extensions/FlexGEMM \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/extensions/FlexGEMM \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/TRELLIS.2/o-voxel \
    && rm -rf /tmp/extensions /tmp/TRELLIS.2

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/pixal3d/runner.py /opt/3dgen-runner/pixal3d_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/pixal3d_runner.py"]

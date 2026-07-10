FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG TRELLIS2_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
ARG TRELLIS2_WEIGHTS_REVISION=af44b45f2e35a493886929c6d786e563ec68364d
ARG UTILS3D_COMMIT=9a4eb15e4021b67b12c460c7057d642626897ec8
ARG NVDIFFRAST_COMMIT=253ac4fcea7de5f396371124af597e6cc957bfae
ARG NVDIFFREC_COMMIT=b296927cc7fd01c2ac1087c8065c4d7248f72da4
ARG CUMESH_COMMIT=12289e1062f0603f2f0d0771b02e1395d247f26f
ARG FLEXGEMM_COMMIT=6dd94a859c26ee8246888502eada3dd8ad85532e
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/TRELLIS.2 \
    TRELLIS2_WEIGHTS_PATH=/workspace/weights/TRELLIS.2-4B \
    OPENCV_IO_ENABLE_OPENEXR=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    ATTN_BACKEND=xformers \
    SPARSE_ATTN_BACKEND=xformers \
    TORCH_CUDA_ARCH_LIST="8.9;12.0" \
    CUDA_HOME=/usr/local/cuda \
    FORCE_CUDA=1 \
    CPATH=/usr/local/cuda/include \
    LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs

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
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone --recurse-submodules https://github.com/microsoft/TRELLIS.2.git /opt/TRELLIS.2 \
    && cd /opt/TRELLIS.2 \
    && git checkout ${TRELLIS2_COMMIT} \
    && git submodule update --init --recursive \
    && test "$(git rev-parse HEAD)" = "${TRELLIS2_COMMIT}"

RUN uv pip install --system "setuptools<81" wheel \
    && uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system xformers==0.0.31 --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system \
        boto3 \
        cmake \
        easydict \
        imageio \
        imageio-ffmpeg \
        kornia \
        lpips \
        ninja \
        opencv-python-headless \
        pandas \
        pillow \
        plyfile \
        scikit-build-core \
        tensorboard \
        timm \
        tqdm \
        transformers \
        trimesh \
        zstandard \
    && uv pip install --system "git+https://github.com/EasternJournalist/utils3d.git@${UTILS3D_COMMIT}"

RUN git clone https://github.com/NVlabs/nvdiffrast.git /tmp/nvdiffrast \
    && git -C /tmp/nvdiffrast checkout ${NVDIFFRAST_COMMIT} \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/nvdiffrast \
    && rm -rf /tmp/nvdiffrast

RUN git clone https://github.com/JeffreyXiang/nvdiffrec.git /tmp/nvdiffrec \
    && git -C /tmp/nvdiffrec checkout ${NVDIFFREC_COMMIT} \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/nvdiffrec \
    && rm -rf /tmp/nvdiffrec

RUN git clone --recurse-submodules https://github.com/JeffreyXiang/CuMesh.git /tmp/CuMesh \
    && git -C /tmp/CuMesh checkout ${CUMESH_COMMIT} \
    && git -C /tmp/CuMesh submodule update --init --recursive \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/CuMesh \
    && rm -rf /tmp/CuMesh

RUN git clone --recurse-submodules https://github.com/JeffreyXiang/FlexGEMM.git /tmp/FlexGEMM \
    && git -C /tmp/FlexGEMM checkout ${FLEXGEMM_COMMIT} \
    && git -C /tmp/FlexGEMM submodule update --init --recursive \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/FlexGEMM \
    && rm -rf /tmp/FlexGEMM

RUN MAX_JOBS=1 uv pip install --system --no-build-isolation --no-deps /opt/TRELLIS.2/o-voxel

RUN uv pip install --system transformers==4.57.3

RUN MAX_JOBS=1 uv pip install --system flash-attn==2.8.3 --no-build-isolation

ENV ATTN_BACKEND=flash_attn \
    SPARSE_ATTN_BACKEND=flash_attn

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/trellis2/runner.py /opt/3dgen-runner/trellis2_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/trellis2_runner.py"]

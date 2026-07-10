FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu22.04

ARG DIRECT3D_S2_COMMIT=a1cf235b2881cff04a91900060a9546b40e7ee5d
ARG DIRECT3D_S2_WEIGHTS_REVISION=8b04a8eddb7a56a0f4e89fe5f5b840c7d5610c00
ARG TORCHSPARSE_COMMIT=385f5ce8718fcae93540511b7f5832f4e71fd835
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/Direct3D-S2 \
    DIRECT3D_S2_WEIGHTS_PATH=/workspace/weights/Direct3D-S2 \
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
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN git clone https://github.com/DreamTechAI/Direct3D-S2.git /opt/Direct3D-S2 \
    && cd /opt/Direct3D-S2 \
    && git checkout ${DIRECT3D_S2_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${DIRECT3D_S2_COMMIT}"

RUN uv pip install --system "setuptools<81" wheel \
    && uv pip install --system \
        torch==2.7.1 \
        torchvision==0.22.1 \
        --index-url https://download.pytorch.org/whl/cu128 \
    && uv pip install --system \
        boto3 \
        diffusers \
        easydict \
        einops \
        huggingface_hub \
        igraph \
        imageio \
        imageio-ffmpeg \
        ninja \
        numpy==1.26.4 \
        omegaconf \
        opencv-python-headless \
        pymeshfix \
        pyvista \
        scikit-image \
        timm \
        tqdm \
        transformers==4.40.2 \
        trimesh \
        triton==3.3.1 \
    && uv pip install --system "git+https://github.com/EasternJournalist/utils3d.git"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsparsehash-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /tmp/extensions \
    && git clone https://github.com/mit-han-lab/torchsparse.git /tmp/extensions/torchsparse \
    && cd /tmp/extensions/torchsparse \
    && git checkout ${TORCHSPARSE_COMMIT} \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation /tmp/extensions/torchsparse \
    && rm -rf /tmp/extensions

RUN MAX_JOBS=1 uv pip install --system --no-build-isolation flash-attn==2.8.3

RUN uv pip install --system --no-build-isolation -e /opt/Direct3D-S2

RUN cd /opt/Direct3D-S2/third_party/voxelize \
    && MAX_JOBS=1 uv pip install --system --no-build-isolation .

RUN uv pip install --system accelerate kornia prettytable

RUN python3 - <<'PY'
import flash_attn
import udf_ext

print("Direct3D-S2 compiled extensions import successfully")
PY

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/direct3d-s2/runner.py /opt/3dgen-runner/direct3d_s2_runner.py

WORKDIR /work
ENTRYPOINT ["python3", "/opt/3dgen-runner/direct3d_s2_runner.py"]

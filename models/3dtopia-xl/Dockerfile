FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

ARG TOPIA_XL_COMMIT=4017e5bfbaab7f73632b47311a92a434abb9d2fc
ARG TOPIA_XL_WEIGHTS_REVISION=8a348b850d36d6354a26917d531eb8f2a5633515
ARG NVDIFFRAST_COMMIT=253ac4fcea7de5f396371124af597e6cc957bfae
ARG CUBVH_COMMIT=757b913bfbf19ed65e3a379d159391a8e29efa0f
ARG PYTORCH3D_COMMIT=33824be3cbc87a7dd1db0f6a9a9de9ac81b2d0ba
ARG PYTHON_VERSION=3.9.23
ARG UV_VERSION=0.11.19

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/workspace/hf \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TORCH_HOME=/workspace/torch \
    U2NET_HOME=/workspace/weights/rembg \
    PYTHONPATH=/opt/bench/src:/opt/3dgen-runner:/opt/3DTopia-XL \
    TOPIA_XL_WEIGHTS_PATH=/workspace/weights/3DTopia-XL \
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
        make \
        openssh-server \
        python3 \
        python3-dev \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | UV_INSTALL_DIR=/usr/local/bin sh

RUN uv python install ${PYTHON_VERSION} \
    && uv venv --python ${PYTHON_VERSION} /opt/venv \
    && uv pip install --python /opt/venv/bin/python "setuptools<81" wheel

RUN git clone https://github.com/3DTopia/3DTopia-XL.git /opt/3DTopia-XL \
    && cd /opt/3DTopia-XL \
    && git checkout ${TOPIA_XL_COMMIT} \
    && test "$(git rev-parse HEAD)" = "${TOPIA_XL_COMMIT}" \
    && grep -R --include='setup.py' -q -- "sm_70" dva/mvp/extensions simple-knn \
    && find dva/mvp/extensions simple-knn -name setup.py -print0 | xargs -0 sed -i 's/sm_70/sm_89/g' \
    && if grep -R --include='setup.py' -q -- "sm_70" dva/mvp/extensions simple-knn; then exit 1; fi

RUN uv pip install --python /opt/venv/bin/python \
        torch==2.1.2 \
        torchvision==0.16.2 \
        torchaudio==2.1.2 \
        --index-url https://download.pytorch.org/whl/cu118 \
    && uv pip install --python /opt/venv/bin/python xformers==0.0.23.post1 --index-url https://download.pytorch.org/whl/cu118 \
    && uv pip install --python /opt/venv/bin/python \
        boto3 \
        diffusers==0.19.3 \
        einops \
        gradio \
        gradio-litmodel3d==0.0.1 \
        imageio \
        imageio-ffmpeg \
        jaxtyping==0.2.31 \
        libigl \
        ninja \
        numpy==1.26.4 \
        omegaconf \
        open_clip_torch \
        opencv-python \
        pygltflib \
        pymeshlab==0.2 \
        PyMCubes \
        'rembg[cpu]' \
        scikit-learn \
        tqdm \
        transformers==4.40.1 \
        trimesh==4.2.0 \
        triton==2.1.0 \
        xatlas

RUN mkdir -p /tmp/extensions \
    && python -c "import torch; from torch.utils.cpp_extension import BuildExtension, CUDAExtension; print('torch cpp extension import ok', torch.__version__)" \
    && git clone https://github.com/NVlabs/nvdiffrast.git /tmp/extensions/nvdiffrast \
    && cd /tmp/extensions/nvdiffrast \
    && git checkout ${NVDIFFRAST_COMMIT} \
    && uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/nvdiffrast \
    && git clone https://github.com/facebookresearch/pytorch3d.git /tmp/extensions/pytorch3d \
    && cd /tmp/extensions/pytorch3d \
    && git checkout ${PYTORCH3D_COMMIT} \
    && MAX_JOBS=1 uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/pytorch3d \
    && git clone --recurse-submodules https://github.com/ashawkey/cubvh.git /tmp/extensions/cubvh \
    && cd /tmp/extensions/cubvh \
    && git checkout ${CUBVH_COMMIT} \
    && git submodule update --init --recursive \
    && uv pip install --python /opt/venv/bin/python --no-build-isolation /tmp/extensions/cubvh \
    && cd /opt/3DTopia-XL/dva/mvp/extensions/mvpraymarch \
    && make -j4 \
    && cd /opt/3DTopia-XL/dva/mvp/extensions/utils \
    && make -j4 \
    && uv pip install --python /opt/venv/bin/python --no-build-isolation /opt/3DTopia-XL/simple-knn \
    && rm -rf /tmp/extensions

COPY bench/src /opt/bench/src
COPY tasks /opt/3dgen-tasks
COPY models/common/runner_utils.py /opt/3dgen-runner/runner_utils.py
COPY models/3dtopia-xl/runner.py /opt/3dgen-runner/3dtopia_xl_runner.py

WORKDIR /work
ENTRYPOINT ["python", "/opt/3dgen-runner/3dtopia_xl_runner.py"]

# Eye tracker (person detection + eye control + web UI).
#
#   docker build -t spookyeyetracker .                                 # CUDA (default)
#   docker build -t spookyeyetracker:cpu --build-arg TORCH_VARIANT=cpu .  # CPU only, ~1.5 GB
#
# Config and calibration live in /config (mount a volume there). Camera credentials and IPs
# come from environment variables - see .env.example.
FROM python:3.13-slim-bookworm

ARG TORCH_VARIANT=cu126
ARG MODEL=yolo11n-pose.pt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    EYETRACKER_CONFIG=/config/config.yaml

# OpenCV runtime libraries
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/tracker

# PyTorch first (largest layer, changes least). cu126 wheels also run on CPU.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/${TORCH_VARIANT}

COPY tracker/requirements.txt .
RUN pip install -r requirements.txt

# Bake the model weights into the image so the container never downloads at runtime.
RUN python -c "from ultralytics import YOLO; YOLO('${MODEL}')" && rm -rf /tmp/ultralytics

COPY tracker/eyetracker ./eyetracker
COPY tracker/config.default.yaml ./config.default.yaml

RUN useradd --create-home --uid 1000 eye \
    && mkdir -p /config /tmp/ultralytics \
    && chown -R eye /config /tmp/ultralytics /app/tracker
USER eye

VOLUME /config
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/state', timeout=4)"

CMD ["python", "-m", "eyetracker"]

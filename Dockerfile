# syntax=docker/dockerfile:1.7
FROM python:3.10-slim

# --- Terraform version (override at build time if needed) ---
ARG TF_VERSION=1.9.5
ARG TARGETARCH
ENV TERRAFORM_ARCH=${TARGETARCH:-amd64}

# --- Minimal OS deps + Terraform ---
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl unzip ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    set -eux; \
    TF_ZIP="terraform_${TF_VERSION}_linux_${TERRAFORM_ARCH}.zip"; \
    BASE_URL="https://releases.hashicorp.com/terraform/${TF_VERSION}"; \
    curl -fsSLO "${BASE_URL}/${TF_ZIP}"; \
    curl -fsSLO "${BASE_URL}/terraform_${TF_VERSION}_SHA256SUMS"; \
    grep " ${TF_ZIP}\$" "terraform_${TF_VERSION}_SHA256SUMS" | sha256sum -c -; \
    unzip -q "$TF_ZIP"; \
    install -m 0755 terraform /usr/local/bin/terraform; \
    rm -f "$TF_ZIP" "terraform_${TF_VERSION}_SHA256SUMS"

# --- Runtime env ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TF_PLUGIN_CACHE_DIR=/root/.terraform.d/plugin-cache

# Terraform plugin cache (optional volume in compose)
RUN mkdir -p "$TF_PLUGIN_CACHE_DIR"

# --- App setup ---
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/status || exit 1

# Flask dev server (simple & sufficient here)
CMD ["python", "app.py"]


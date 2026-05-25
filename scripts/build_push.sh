#!/usr/bin/env bash
# Script to build and push AMD64 container to registry.beakcloud.com

set -euo pipefail

REGISTRY="registry.beakcloud.com"
IMAGE_NAME="tucano-yfinance"
TAG="latest"
FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "=========================================================="
echo "Building and Pushing AMD64 image to Beakcloud Registry"
echo "Target Image: ${FULL_IMAGE_NAME}"
echo "=========================================================="

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo "Error: Docker daemon is not running."
    exit 1
fi

echo "==> Building container for linux/amd64..."
# We use docker buildx to compile specifically for the AMD64 target platform
docker buildx build --platform linux/amd64 -t "${FULL_IMAGE_NAME}" --load .

echo "==> Pushing container image to registry..."
docker push "${FULL_IMAGE_NAME}"

echo "=========================================================="
echo "Successfully completed! Image available at: ${FULL_IMAGE_NAME}"
echo "=========================================================="

#!/bin/bash

# ==========================================================
# Script: tb_reset.sh
# Purpose: Completely clean up the environment by uninstalling 
#          all Helm releases and deleting specific services.
# Run method:
# chmod +x tb_reset.sh
# ./tb_reset.sh
# ==========================================================

echo "--- Starting Environment Cleanup ---"

# 1. 取得所有 Helm release 並進行卸載
echo "[1/4] Uninstalling all Helm releases..."
RELEASES=$(helm list -q)
if [ -z "$RELEASES" ]; then
    echo "No Helm releases found."
else
    for RELEASE in $RELEASES; do
        echo "Uninstalling release: $RELEASE"
        helm uninstall "$RELEASE"
    done
fi

# 2. 刪除手動部署的 Kubernetes 資源 (根據 f1-proxy.yaml)
echo "[2/4] Deleting k8s resources from f1-proxy.yaml..."
# 使用 -f 可以直接刪除該 yaml 裡面定義的所有資源
kubectl delete -f f1-proxy/f1-proxy.yaml --ignore-not-found=true

# 3. 刪除特定的 Kubernetes Service (保留你原有的邏輯)
echo "[3/4] Deleting OAI RAN services..."
kubectl delete svc oai-ran --ignore-not-found=true

# 4. 刪除所有名為 f1-proxy 的 Docker Images
echo "[4/4] Removing all Docker images for 'f1-proxy'..."

# 取得所有 repository 名稱為 f1-proxy 的 Image ID
IMAGE_IDS=$(docker images -q f1-proxy)

if [ -z "$IMAGE_IDS" ]; then
    echo "No f1-proxy images found, skipping."
else
    echo "Deleting the following Image IDs:"
    echo "$IMAGE_IDS"
    # 使用 -f (force) 是為了確保即使有容器曾經使用過該 image 名稱也能嘗試刪除
    docker rmi -f $IMAGE_IDS
fi

echo "------------------------------------------------"
echo "Cleanup Complete! Your environment is now fresh."
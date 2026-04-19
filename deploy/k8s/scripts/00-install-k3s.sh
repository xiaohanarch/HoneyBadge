#!/bin/bash
# ============================================================
# Step 0: Install k3s on ECS (run this on the ECS server)
# ECS: 8.130.95.169  |  OS: Ubuntu/CentOS/Alibaba Cloud Linux
# ============================================================
set -e

echo "=== Installing k3s ==="
# k3s with Traefik enabled (handles Ingress on port 80/443)
# NodePorts 30167 (Matrix) and 30888 (Element Web) bypass Traefik directly
curl -sfL https://rancher-mirror.rancher.cn/k3s/k3s-install.sh | \
  INSTALL_K3S_MIRROR=cn \
  sh -s - \
    --write-kubeconfig-mode 644

echo "=== Waiting for k3s to start ==="
sleep 15
k3s kubectl get nodes

echo "=== Setting up kubectl alias ==="
mkdir -p ~/.kube
cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
chmod 600 ~/.kube/config

echo "=== Installing kustomize ==="
curl -s "https://raw.githubusercontent.com/kubernetes-sigs/kustomize/master/hack/install_kustomize.sh" | bash
mv kustomize /usr/local/bin/

echo ""
echo "=== k3s installed! ==="
echo "Node status:"
kubectl get nodes
echo ""
echo "Next step: run 01-setup-acr-secret.sh"

#!/bin/bash
# Enable and configure Kubernetes authentication
set -e

echo "Enabling Kubernetes authentication..."
vault auth enable kubernetes || echo "Kubernetes auth already enabled"

echo "Configuring Kubernetes auth..."
vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc:443"

echo "Kubernetes authentication configured."
vault auth list

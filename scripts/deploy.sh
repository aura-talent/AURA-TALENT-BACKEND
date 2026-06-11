#!/bin/bash
# Manual deployment script for GCP VM
# Usage: ./scripts/deploy.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
VM_NAME="career-ops-backend"
VM_ZONE="us-central1-a"
PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project)}"

echo -e "${YELLOW}Starting deployment to GCP VM...${NC}"
echo "Project: $PROJECT_ID"
echo "VM: $VM_NAME"
echo "Zone: $VM_ZONE"
echo ""

# Get VM IP
echo "Getting VM IP address..."
VM_IP=$(gcloud compute instances describe $VM_NAME \
  --zone=$VM_ZONE \
  --project=$PROJECT_ID \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

if [ -z "$VM_IP" ]; then
  echo -e "${RED}Failed to get VM IP address${NC}"
  exit 1
fi

echo -e "${GREEN}VM IP: $VM_IP${NC}"
echo ""

# SSH and deploy
echo "Deploying to VM..."
gcloud compute ssh $VM_NAME --zone=$VM_ZONE --project=$PROJECT_ID << 'ENDSSH'
set -e

echo "📦 Pulling latest code..."
cd /opt/career-ops-backend

if [ -d ".git" ]; then
  git fetch origin main
  git reset --hard origin/main
else
  echo "Git repository not initialized. Please clone manually first."
  exit 1
fi

cd backend

echo "🔧 Installing dependencies..."
~/.cargo/bin/uv sync

echo "🔄 Restarting service..."
sudo systemctl restart career-ops-backend

echo "⏳ Waiting for service to start..."
sleep 5

# Check service status
if sudo systemctl is-active --quiet career-ops-backend; then
  echo "✅ Service is running!"
else
  echo "❌ Service failed to start!"
  sudo journalctl -u career-ops-backend -n 20 --no-pager
  exit 1
fi
ENDSSH

# Health check
echo ""
echo "Running health check..."
if curl -f -s http://$VM_IP:8000/health > /dev/null; then
  echo -e "${GREEN}✅ Deployment successful!${NC}"
  echo ""
  echo "API: http://$VM_IP:8000"
  echo "Docs: http://$VM_IP:8000/docs"
else
  echo -e "${RED}❌ Health check failed${NC}"
  exit 1
fi

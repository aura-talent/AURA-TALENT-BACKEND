# GCP VM Deployment Guide

This guide walks you through deploying the career-ops backend to a GCP VM with automatic GitHub Actions deployment.

## Part 1: Set Up GCP VM

### 1.1 Create a VM Instance

```bash
# Set your project ID
gcloud config set project YOUR_PROJECT_ID

# Create a VM instance (e2-medium is good for FastAPI apps)
gcloud compute instances create career-ops-backend \
  --zone=us-central1-a \
  --machine-type=e2-medium \
  --boot-disk-size=20GB \
  --boot-disk-type=pd-balanced \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --tags=http-server,https-server \
  --metadata=startup-script='#!/bin/bash
apt-get update
apt-get install -y python3-pip python3-venv git nginx
'
```

**Or via GCP Console:**
1. Go to Compute Engine → VM Instances
2. Click "CREATE INSTANCE"
3. Configure:
   - Name: `career-ops-backend`
   - Region: Choose closest to your users (e.g., `us-central1`)
   - Machine type: `e2-medium` (2 vCPU, 4 GB memory)
   - Boot disk: Ubuntu 22.04 LTS, 20 GB
   - Firewall: ✓ Allow HTTP traffic, ✓ Allow HTTPS traffic
4. Click "CREATE"

### 1.2 Configure Firewall Rules

```bash
# Allow port 8000 (FastAPI) - you'll proxy this through nginx later
gcloud compute firewall-rules create allow-fastapi \
  --allow=tcp:8000 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=http-server
```

### 1.3 SSH into the VM

```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a
```

### 1.4 Set Up the VM (run on VM)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env

# Create app directory
sudo mkdir -p /opt/career-ops-backend
sudo chown $USER:$USER /opt/career-ops-backend
cd /opt/career-ops-backend

# Clone your repository (you'll need to set this up first)
# git clone https://github.com/YOUR_USERNAME/career-ops.git .
# cd backend

# For now, create the directory structure
mkdir -p app
```

### 1.5 Set Up Environment Variables (run on VM)

```bash
cd /opt/career-ops-backend/backend
nano .env
```

Add your environment variables:
```
ANTHROPIC_API_KEY=your_actual_key
BACKEND_API_KEY=your_secure_key
MODEL_NAME=anthropic:claude-sonnet-4-6
```

### 1.6 Set Up Systemd Service (run on VM)

```bash
sudo nano /etc/systemd/system/career-ops-backend.service
```

Add this configuration:
```ini
[Unit]
Description=Career Ops FastAPI Backend
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/opt/career-ops-backend/backend
Environment="PATH=/home/YOUR_USERNAME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/YOUR_USERNAME/.cargo/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_USERNAME` with your actual username (run `whoami` to check).

### 1.7 Start the Service (run on VM)

```bash
sudo systemctl daemon-reload
sudo systemctl enable career-ops-backend
sudo systemctl start career-ops-backend
sudo systemctl status career-ops-backend
```

### 1.8 Set Up Nginx Reverse Proxy (Optional but Recommended)

```bash
sudo nano /etc/nginx/sites-available/career-ops-backend
```

Add:
```nginx
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable and restart:
```bash
sudo ln -s /etc/nginx/sites-available/career-ops-backend /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## Part 2: Set Up GitHub Actions

### 2.1 Create Service Account for GitHub Actions

```bash
# On your local machine
gcloud iam service-accounts create github-actions-deployer \
  --display-name="GitHub Actions Deployer"

# Grant necessary permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin.v1"

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:github-actions-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# Create and download key
gcloud iam service-accounts keys create ~/gcp-key.json \
  --iam-account=github-actions-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

### 2.2 Add SSH Key for GitHub Actions

```bash
# Generate SSH key (on your local machine)
ssh-keygen -t ed25519 -f ~/.ssh/gcp-github-actions -N "" -C "github-actions"

# Add public key to VM
gcloud compute instances add-metadata career-ops-backend \
  --zone=us-central1-a \
  --metadata-from-file ssh-keys=<(echo "github-actions:$(cat ~/.ssh/gcp-github-actions.pub)")
```

### 2.3 Add GitHub Secrets

Go to your GitHub repository → Settings → Secrets and variables → Actions → New repository secret

Add these secrets:
- `GCP_PROJECT_ID`: Your GCP project ID
- `GCP_SA_KEY`: Contents of `~/gcp-key.json` file
- `GCP_SSH_PRIVATE_KEY`: Contents of `~/.ssh/gcp-github-actions` file
- `GCP_VM_ZONE`: `us-central1-a` (or your chosen zone)
- `GCP_VM_NAME`: `career-ops-backend`
- `BACKEND_API_KEY`: Your backend API key
- `ANTHROPIC_API_KEY`: Your Anthropic API key

### 2.4 Test Deployment

```bash
# Get your VM's external IP
gcloud compute instances describe career-ops-backend \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'

# Test the API
curl http://YOUR_VM_IP:8000/health
# Or if using nginx:
curl http://YOUR_VM_IP/health
```

## Part 3: Monitoring and Maintenance

### View Logs
```bash
# SSH into VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# View service logs
sudo journalctl -u career-ops-backend -f

# View nginx logs (if using nginx)
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Restart Service
```bash
sudo systemctl restart career-ops-backend
```

### Update Environment Variables
```bash
cd /opt/career-ops-backend/backend
nano .env
sudo systemctl restart career-ops-backend
```

## Security Considerations

1. **API Keys**: Never commit `.env` to git
2. **Firewall**: Consider restricting access to specific IPs
3. **HTTPS**: Set up SSL with Let's Encrypt (certbot)
4. **GitHub Secrets**: Rotate secrets regularly
5. **Service Account**: Use minimal permissions

## Cost Estimation

- **e2-medium VM**: ~$24/month (730 hours)
- **20 GB Standard Persistent Disk**: ~$0.80/month
- **Network egress**: Varies by usage

## Troubleshooting

### Service won't start
```bash
sudo journalctl -u career-ops-backend -n 50 --no-pager
```

### Can't connect to API
```bash
# Check if service is running
sudo systemctl status career-ops-backend

# Check if port is open
sudo netstat -tlnp | grep 8000

# Check firewall
gcloud compute firewall-rules list
```

### GitHub Actions fails
- Check secrets are set correctly
- Verify service account permissions
- Check VM is running: `gcloud compute instances list`

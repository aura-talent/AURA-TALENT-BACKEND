# Quick Start: Deploy to GCP with GitHub Actions

This guide gets your backend deployed in ~15 minutes.

## Prerequisites

- Google Cloud Platform account with billing enabled
- GitHub repository
- `gcloud` CLI installed ([install guide](https://cloud.google.com/sdk/docs/install))

## Step 1: Create GCP VM (5 minutes)

```bash
# Set your project
gcloud config set project YOUR_PROJECT_ID

# Create VM
gcloud compute instances create career-ops-backend \
  --zone=us-central1-a \
  --machine-type=e2-medium \
  --boot-disk-size=20GB \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --tags=http-server,https-server

# Allow port 8000
gcloud compute firewall-rules create allow-fastapi \
  --allow=tcp:8000 \
  --source-ranges=0.0.0.0/0 \
  --target-tags=http-server
```

## Step 2: Set Up the VM (5 minutes)

```bash
# SSH into VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Run setup script (paste the entire script or upload it)
curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/career-ops/main/backend/scripts/setup-vm.sh | bash

# Or manually run the commands from setup-vm.sh
```

**Important:** Edit the `.env` file on the VM:
```bash
nano /opt/career-ops-backend/backend/.env
# Add your actual API keys
sudo systemctl restart career-ops-backend
```

## Step 3: Configure GitHub Actions (5 minutes)

### 3.1 Create Service Account

```bash
# Back on your local machine
gcloud iam service-accounts create github-actions-deployer \
  --display-name="GitHub Actions Deployer"

# Grant permissions
export PROJECT_ID=$(gcloud config get-value project)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin.v1"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

# Create key
gcloud iam service-accounts keys create ~/gcp-key.json \
  --iam-account=github-actions-deployer@$PROJECT_ID.iam.gserviceaccount.com
```

### 3.2 Create SSH Key for GitHub Actions

```bash
# Generate SSH key
ssh-keygen -t ed25519 -f ~/.ssh/gcp-github-actions -N "" -C "github-actions"

# Add to VM
gcloud compute instances add-metadata career-ops-backend \
  --zone=us-central1-a \
  --metadata-from-file ssh-keys=<(echo "github-actions:$(cat ~/.ssh/gcp-github-actions.pub)")
```

### 3.3 Add GitHub Secrets

Go to: `https://github.com/YOUR_USERNAME/YOUR_REPO/settings/secrets/actions/new`

Add these secrets:

| Secret Name | Value | How to Get |
|-------------|-------|------------|
| `GCP_PROJECT_ID` | Your project ID | `gcloud config get-value project` |
| `GCP_SA_KEY` | Service account JSON | `cat ~/gcp-key.json` |
| `GCP_SSH_PRIVATE_KEY` | SSH private key | `cat ~/.ssh/gcp-github-actions` |
| `GCP_VM_ZONE` | `us-central1-a` | (or your chosen zone) |
| `GCP_VM_NAME` | `career-ops-backend` | (your VM name) |
| `BACKEND_API_KEY` | Your API key | Same as in VM's `.env` |
| `ANTHROPIC_API_KEY` | Your Anthropic key | Same as in VM's `.env` |

## Step 4: Test Deployment

```bash
# Get your VM IP
gcloud compute instances describe career-ops-backend \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'

# Test the API
curl http://YOUR_VM_IP:8000/health

# View API docs
open http://YOUR_VM_IP:8000/docs
```

## Step 5: Trigger Auto-Deploy

```bash
# Make a small change and push to main
echo "# Auto-deploy test" >> README.md
git add .
git commit -m "Test auto-deploy"
git push origin main
```

Watch the deployment in GitHub Actions: `https://github.com/YOUR_USERNAME/YOUR_REPO/actions`

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│ GitHub Repository (main branch)                             │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Push to main
             ↓
┌─────────────────────────────────────────────────────────────┐
│ GitHub Actions                                              │
│ 1. Checkout code                                            │
│ 2. Authenticate with GCP                                    │
│ 3. SSH to VM                                                │
│ 4. Pull latest code                                         │
│ 5. Run: uv sync                                             │
│ 6. Restart service                                          │
│ 7. Health check                                             │
└────────────┬────────────────────────────────────────────────┘
             │
             │ Deploys to
             ↓
┌─────────────────────────────────────────────────────────────┐
│ GCP VM (e2-medium, Ubuntu 22.04)                           │
│                                                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Nginx :80 ─────► FastAPI :8000                     │   │
│  │                                                     │   │
│  │  Systemd Service (career-ops-backend)             │   │
│  │  ├─ uv run uvicorn                                 │   │
│  │  ├─ Auto-restart on failure                        │   │
│  │  └─ Logs: journalctl -u career-ops-backend        │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  /opt/career-ops-backend/backend/                          │
│  ├─ app/                                                   │
│  ├─ .env (secrets)                                         │
│  ├─ pyproject.toml                                         │
│  └─ uv.lock                                                │
└─────────────────────────────────────────────────────────────┘
```

## Common Commands

### On Your Local Machine

```bash
# Manual deployment
./scripts/deploy.sh

# Check VM status
gcloud compute instances list

# View GitHub Actions logs
gh run list
gh run view --log
```

### On the VM (SSH)

```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# View service status
sudo systemctl status career-ops-backend

# View logs (live)
sudo journalctl -u career-ops-backend -f

# Restart service
sudo systemctl restart career-ops-backend

# Update dependencies
cd /opt/career-ops-backend/backend
~/.cargo/bin/uv sync
sudo systemctl restart career-ops-backend

# Edit environment variables
nano /opt/career-ops-backend/backend/.env
sudo systemctl restart career-ops-backend
```

## Troubleshooting

### Deployment fails in GitHub Actions

**Check secrets:**
```bash
# Verify secrets are set in GitHub UI
# Settings → Secrets and variables → Actions
```

**Check VM is running:**
```bash
gcloud compute instances list
```

**Check service account permissions:**
```bash
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:github-actions-deployer@*"
```

### Service won't start on VM

```bash
# Check logs
sudo journalctl -u career-ops-backend -n 50 --no-pager

# Check if port is in use
sudo netstat -tlnp | grep 8000

# Test manually
cd /opt/career-ops-backend/backend
~/.cargo/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Can't access API

```bash
# Check firewall rules
gcloud compute firewall-rules list

# Check nginx (if using)
sudo systemctl status nginx
sudo nginx -t

# Check if service is listening
curl http://localhost:8000/health  # From within VM
```

## Security Checklist

- [ ] Changed default `BACKEND_API_KEY` in `.env`
- [ ] Restricted firewall rules to specific IPs (optional)
- [ ] Set up HTTPS with Let's Encrypt (recommended for production)
- [ ] Rotate GitHub secrets every 90 days
- [ ] Enable GCP Cloud Logging
- [ ] Set up uptime monitoring
- [ ] Configure automatic backups

## Next Steps

1. **Add HTTPS**: Use certbot for free SSL certificates
2. **Add Monitoring**: Set up GCP Cloud Monitoring alerts
3. **Add Domain**: Point your domain to the VM IP
4. **Scale Up**: Use Cloud Load Balancer + multiple VMs for high availability
5. **CI/CD Improvements**: Add tests, linting, staging environment

## Cost Optimization

**Current setup (~$25/month):**
- Use `e2-small` instead of `e2-medium` for lighter loads (~$12/month)
- Use preemptible VMs for dev/staging (up to 80% cheaper)
- Stop VM during off-hours: `gcloud compute instances stop career-ops-backend`

**Need help?** Check `DEPLOYMENT.md` for detailed documentation.

# 🎉 Deployment Setup Status

## ✅ Completed Steps

### 1. GCP VM Created
- **VM Name**: `career-ops-backend`
- **Zone**: `us-central1-a`
- **Machine Type**: `e2-medium`
- **External IP**: `34.132.193.54`
- **Internal IP**: `10.128.0.2`
- **Status**: ✅ RUNNING

### 2. Firewall Rules Configured
- ✅ HTTP traffic allowed (port 80)
- ✅ HTTPS traffic allowed (port 443)
- ✅ FastAPI port allowed (port 8000)

### 3. Repository Cloned
- ✅ Repository cloned to `/opt/career-ops-backend`
- ✅ Using credentials: `charleshor0311`
- ✅ Repository: `https://github.com/aura-talent/AURA-TALENT-BACKEND.git`

### 4. Dependencies Installed
- ✅ uv installed at `/home/charleshor/.local/bin/uv`
- ✅ Python dependencies installed (96 packages)
- ✅ Virtual environment created at `/opt/career-ops-backend/.venv`

### 5. System Services Configured
- ✅ Systemd service created: `/etc/systemd/system/career-ops-backend.service`
- ✅ Nginx installed and configured
- ✅ Nginx reverse proxy set up (port 80 → port 8000)

### 6. GitHub Actions Preparation
- ✅ Service account created: `github-actions-deployer@project-959ef152-d27b-437b-acc.iam.gserviceaccount.com`
- ✅ IAM roles granted (compute.instanceAdmin.v1, iam.serviceAccountUser)
- ✅ SSH key generated for GitHub Actions: `~/.ssh/gcp-github-actions`
- ✅ SSH key added to VM metadata

---

## ⚠️ TODO: Complete Setup

### Step 1: Update Environment Variables

**I need your API keys!** Please provide:

1. **Anthropic API Key** (starts with `sk-ant-...`)
2. **Backend API Key** (create a secure random string)

Once you provide these, run:

```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Edit .env file
nano /opt/career-ops-backend/.env

# Update these lines:
ANTHROPIC_API_KEY=your_real_key_here
BACKEND_API_KEY=your_secure_key_here
```

### Step 2: Start the Service

```bash
# Enable and start the service
sudo systemctl enable career-ops-backend
sudo systemctl start career-ops-backend

# Check status
sudo systemctl status career-ops-backend

# View logs
sudo journalctl -u career-ops-backend -f
```

### Step 3: Test the API

```bash
# From your local machine
curl http://34.132.193.54:8000/health

# Or open in browser
open http://34.132.193.54:8000/docs
```

### Step 4: Set Up GitHub Actions

Add these secrets to your GitHub repository:
`https://github.com/aura-talent/AURA-TALENT-BACKEND/settings/secrets/actions`

| Secret Name | Value | Location |
|-------------|-------|----------|
| `GCP_PROJECT_ID` | `project-959ef152-d27b-437b-acc` | - |
| `GCP_VM_ZONE` | `us-central1-a` | - |
| `GCP_VM_NAME` | `career-ops-backend` | - |
| `GCP_SSH_PRIVATE_KEY` | Full contents of the file | `cat ~/.ssh/gcp-github-actions` |
| `BACKEND_API_KEY` | Same as in .env | (you'll provide) |
| `ANTHROPIC_API_KEY` | Same as in .env | (you'll provide) |

**Note**: Since service account key creation is disabled (good security!), we'll use SSH-based deployment.

### Step 5: Update GitHub Workflow

The workflow at `.github/workflows/deploy.yml` needs to be updated to use SSH authentication without the service account key. The current setup uses:

- SSH key for connection: ✅ Ready
- GitHub personal access token for git clone: ✅ Already working

---

## 📋 Quick Commands

### SSH to VM
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a
```

### View Service Status
```bash
sudo systemctl status career-ops-backend
```

### View Logs
```bash
sudo journalctl -u career-ops-backend -f
```

### Restart Service
```bash
sudo systemctl restart career-ops-backend
```

### Test API
```bash
curl http://34.132.193.54:8000/health
```

### Update Code Manually
```bash
cd /opt/career-ops-backend
git pull
uv sync
sudo systemctl restart career-ops-backend
```

---

## 🔧 Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u career-ops-backend -n 50 --no-pager

# Check .env file exists
ls -la /opt/career-ops-backend/.env

# Test manually
cd /opt/career-ops-backend
~/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Can't access API
```bash
# Check if service is running
sudo systemctl status career-ops-backend

# Check if port is listening
sudo netstat -tlnp | grep 8000

# Check nginx
sudo systemctl status nginx
sudo nginx -t
```

---

## 🎯 Next Steps After API Keys

1. ✅ Provide API keys
2. Update .env on VM
3. Start the service
4. Test the API endpoint
5. Set up GitHub secrets
6. Push to main branch to test auto-deploy

---

## 📞 Your VM Information

- **External IP**: `34.132.193.54`
- **API URL**: `http://34.132.193.54:8000`
- **API Docs**: `http://34.132.193.54:8000/docs`
- **Health Check**: `http://34.132.193.54:8000/health`
- **SSH Command**: `gcloud compute ssh career-ops-backend --zone=us-central1-a`

---

## 💰 Monthly Cost Estimate

- **e2-medium VM**: ~$24/month
- **20GB disk**: ~$0.80/month
- **Network egress**: Varies by usage
- **Total**: ~$25-30/month

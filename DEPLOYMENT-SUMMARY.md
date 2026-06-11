# 🚀 Deployment Package Complete!

Everything you need to deploy your Career Ops backend to GCP with automatic GitHub Actions deployment.

## 📦 What's Included

### Documentation
1. **QUICKSTART-DEPLOY.md** - 15-minute setup guide (START HERE!)
2. **DEPLOYMENT.md** - Detailed deployment documentation
3. **DEPLOY-CHECKLIST.md** - Step-by-step checklist
4. **DEPENDENCIES.md** - uv dependency management guide

### Automation Files
5. **.github/workflows/deploy.yml** - GitHub Actions auto-deploy workflow
6. **scripts/deploy.sh** - Manual deployment script
7. **scripts/setup-vm.sh** - Initial VM configuration script

### Configuration
8. **pyproject.toml** - Modern Python dependencies (uv-based)
9. **.gitignore** - Updated to exclude secrets and deployment artifacts
10. **app/main.py** - Enhanced health endpoint for monitoring

## 🎯 Quick Start Path

### For the Impatient (15 minutes)
```bash
# 1. Follow QUICKSTART-DEPLOY.md
open QUICKSTART-DEPLOY.md

# 2. Use the checklist to track progress
open DEPLOY-CHECKLIST.md
```

### For the Thorough (30 minutes)
```bash
# 1. Read the detailed guide
open DEPLOYMENT.md

# 2. Follow the checklist
open DEPLOY-CHECKLIST.md

# 3. Use automation scripts
./scripts/setup-vm.sh    # On VM
./scripts/deploy.sh      # For manual deploys
```

## 🏗️ Architecture Overview

```
┌─────────────────────┐
│   Your Computer     │
│  git push origin    │
│       main          │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  GitHub Actions     │
│  - Checkout code    │
│  - Auth with GCP    │
│  - SSH to VM        │
│  - Deploy & test    │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│    GCP VM           │
│  ┌───────────────┐  │
│  │ Nginx :80     │  │
│  │      ↓        │  │
│  │ FastAPI :8000 │  │
│  │      ↓        │  │
│  │  uv + Python  │  │
│  └───────────────┘  │
│                     │
│  /opt/career-ops-   │
│    backend/         │
└─────────────────────┘
```

## ⚙️ What Happens on Deploy

1. **Trigger**: Push to `main` branch
2. **GitHub Actions**:
   - Authenticates with GCP
   - SSHs to VM
   - Pulls latest code
   - Installs/updates dependencies with `uv sync`
   - Restarts the systemd service
   - Runs health check
3. **VM**: Service restarts automatically, zero downtime for small deploys
4. **Monitoring**: GitHub Actions reports success/failure

## 🔑 Required Secrets (GitHub Repository)

Add these in: `Settings → Secrets and variables → Actions`

| Secret | Description | How to Get |
|--------|-------------|------------|
| `GCP_PROJECT_ID` | Your GCP project | `gcloud config get-value project` |
| `GCP_SA_KEY` | Service account JSON | Created in setup |
| `GCP_SSH_PRIVATE_KEY` | SSH key for deployment | Created in setup |
| `GCP_VM_ZONE` | VM zone | e.g., `us-central1-a` |
| `GCP_VM_NAME` | VM instance name | e.g., `career-ops-backend` |
| `BACKEND_API_KEY` | Your API key | From `.env` |
| `ANTHROPIC_API_KEY` | Your Anthropic key | From `.env` |

## 🧪 Testing Your Deployment

### Manual Test
```bash
# Get your VM IP
VM_IP=$(gcloud compute instances describe career-ops-backend \
  --zone=us-central1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)')

# Test health endpoint
curl http://$VM_IP:8000/health

# Test API docs
open http://$VM_IP:8000/docs
```

### Automatic Test
```bash
# Push to main and watch GitHub Actions
git add .
git commit -m "Test deployment"
git push origin main

# Watch the action
gh run watch
```

## 📊 Monitoring

### View Logs
```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Live logs
sudo journalctl -u career-ops-backend -f

# Recent logs
sudo journalctl -u career-ops-backend -n 100 --no-pager
```

### Service Status
```bash
sudo systemctl status career-ops-backend
```

### Health Check
```bash
curl http://localhost:8000/health
```

## 🔧 Common Operations

### Manual Deployment
```bash
./scripts/deploy.sh
```

### Update Dependencies
```bash
# On VM
cd /opt/career-ops-backend/backend
~/.cargo/bin/uv sync
sudo systemctl restart career-ops-backend
```

### Update Environment Variables
```bash
# On VM
nano /opt/career-ops-backend/backend/.env
sudo systemctl restart career-ops-backend
```

### Rollback
```bash
# On VM
cd /opt/career-ops-backend
git log --oneline -5
git reset --hard PREVIOUS_COMMIT
cd backend
~/.cargo/bin/uv sync
sudo systemctl restart career-ops-backend
```

## 🛡️ Security Checklist

- ✅ `.env` file is gitignored
- ✅ API keys are in GitHub Secrets, not code
- ✅ Service account has minimal permissions
- ✅ SSH keys are separate for deployment
- ✅ `.gitignore` excludes all credential files
- ⚠️ TODO: Set up HTTPS with Let's Encrypt
- ⚠️ TODO: Restrict firewall to specific IPs (optional)

## 💰 Cost Estimate

### Current Setup
- **VM (e2-medium)**: ~$24/month
- **Disk (20GB)**: ~$0.80/month
- **Network**: Varies by traffic
- **Total**: ~$25-30/month

### Cost Optimization
- Use `e2-small` for lighter loads (~$12/month)
- Stop VM during off-hours if not 24/7
- Use preemptible VMs for dev/staging (80% cheaper)

## 🚨 Troubleshooting

### GitHub Actions Fails
1. Check secrets are set correctly
2. Verify VM is running: `gcloud compute instances list`
3. Check service account permissions
4. Review Actions logs for specific error

### Service Won't Start
```bash
# Check logs
sudo journalctl -u career-ops-backend -n 50 --no-pager

# Check .env file exists
ls -la /opt/career-ops-backend/backend/.env

# Test manually
cd /opt/career-ops-backend/backend
~/.cargo/bin/uv run uvicorn app.main:app
```

### Can't Access API
```bash
# Check firewall
gcloud compute firewall-rules list

# Check service is running
sudo systemctl status career-ops-backend

# Check port is listening
sudo netstat -tlnp | grep 8000
```

## 📚 Additional Resources

- [GCP VM Documentation](https://cloud.google.com/compute/docs)
- [GitHub Actions Docs](https://docs.github.com/actions)
- [uv Documentation](https://docs.astral.sh/uv/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)

## 🎉 Next Steps After Deployment

1. **Add HTTPS**: Use certbot for free SSL
2. **Custom Domain**: Point your domain to VM IP
3. **Monitoring**: Set up GCP Cloud Monitoring
4. **Backups**: Configure automated database backups
5. **Scaling**: Add load balancer for multiple VMs
6. **CI/CD**: Add tests to GitHub Actions workflow

## 📞 Need Help?

- Check `DEPLOYMENT.md` for detailed documentation
- Review `DEPLOY-CHECKLIST.md` to ensure nothing was missed
- Check GitHub Actions logs for deployment errors
- Review VM logs: `sudo journalctl -u career-ops-backend`

---

**Ready to deploy?** Start with `QUICKSTART-DEPLOY.md` 🚀

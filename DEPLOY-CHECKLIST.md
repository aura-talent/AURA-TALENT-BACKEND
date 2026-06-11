# Deployment Checklist

Use this checklist to ensure a smooth deployment to GCP.

## Pre-Deployment (On Your Local Machine)

### 1. GCP Setup
- [ ] GCP account created and billing enabled
- [ ] `gcloud` CLI installed and authenticated
  ```bash
  gcloud auth login
  gcloud config set project YOUR_PROJECT_ID
  ```
- [ ] Project ID noted: `________________`

### 2. Create and Configure VM
- [ ] VM created (e2-medium recommended)
  ```bash
  gcloud compute instances create career-ops-backend \
    --zone=us-central1-a \
    --machine-type=e2-medium \
    --boot-disk-size=20GB \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --tags=http-server,https-server
  ```
- [ ] Firewall rules created
  ```bash
  gcloud compute firewall-rules create allow-fastapi \
    --allow=tcp:8000 \
    --source-ranges=0.0.0.0/0 \
    --target-tags=http-server
  ```
- [ ] VM IP noted: `________________`

### 3. Initial VM Setup
- [ ] SSH into VM: `gcloud compute ssh career-ops-backend --zone=us-central1-a`
- [ ] Run setup script or manual commands from `scripts/setup-vm.sh`
- [ ] Repository cloned to `/opt/career-ops-backend`
- [ ] `.env` file created with real API keys
- [ ] Dependencies installed with `uv sync`
- [ ] Systemd service created and started
- [ ] Service is running: `sudo systemctl status career-ops-backend`
- [ ] Health check works: `curl http://localhost:8000/health`

### 4. GitHub Actions Setup

#### 4.1 Service Account
- [ ] Service account created
  ```bash
  gcloud iam service-accounts create github-actions-deployer \
    --display-name="GitHub Actions Deployer"
  ```
- [ ] Permissions granted (compute.instanceAdmin.v1, iam.serviceAccountUser)
- [ ] Service account key created: `~/gcp-key.json`

#### 4.2 SSH Key
- [ ] SSH key generated: `~/.ssh/gcp-github-actions`
- [ ] Public key added to VM metadata

#### 4.3 GitHub Secrets
Go to: `https://github.com/YOUR_USERNAME/YOUR_REPO/settings/secrets/actions`

- [ ] `GCP_PROJECT_ID` added
- [ ] `GCP_SA_KEY` added (contents of `~/gcp-key.json`)
- [ ] `GCP_SSH_PRIVATE_KEY` added (contents of `~/.ssh/gcp-github-actions`)
- [ ] `GCP_VM_ZONE` added (e.g., `us-central1-a`)
- [ ] `GCP_VM_NAME` added (e.g., `career-ops-backend`)
- [ ] `BACKEND_API_KEY` added
- [ ] `ANTHROPIC_API_KEY` added

### 5. GitHub Workflow
- [ ] `.github/workflows/deploy.yml` exists and committed
- [ ] Workflow file pushed to main branch
- [ ] Repository has correct structure with `backend/` directory

## Testing Deployment

### Manual Tests
- [ ] Health check works from outside: `curl http://VM_IP:8000/health`
- [ ] API docs accessible: `http://VM_IP:8000/docs`
- [ ] Can upload resume (test with API docs)
- [ ] Can evaluate job (test with API docs)

### GitHub Actions Test
- [ ] Make a test commit and push to main
  ```bash
  echo "# Deployment test" >> README.md
  git add .
  git commit -m "Test deployment"
  git push origin main
  ```
- [ ] GitHub Actions workflow runs successfully
- [ ] Check Actions tab: `https://github.com/YOUR_USERNAME/YOUR_REPO/actions`
- [ ] Deployment summary shows success
- [ ] Health check passes in workflow

## Post-Deployment

### Monitoring Setup
- [ ] Set up GCP Cloud Monitoring alert for VM down
- [ ] Set up uptime monitoring for health endpoint
- [ ] Configure log retention policy
- [ ] Set budget alert in GCP billing

### Security Hardening
- [ ] Changed default `BACKEND_API_KEY` from "change-me"
- [ ] API keys never committed to repository
- [ ] `.env` file gitignored
- [ ] Consider restricting firewall to specific IPs
- [ ] Set up HTTPS with Let's Encrypt (optional but recommended)
  ```bash
  sudo apt-get install certbot python3-certbot-nginx
  sudo certbot --nginx -d yourdomain.com
  ```

### Documentation
- [ ] Update frontend configuration with new API endpoint
- [ ] Document API endpoint URL for team
- [ ] Note any CORS configuration needed
- [ ] Create runbook for common issues

## Maintenance

### Regular Tasks
- [ ] Monitor service logs: `sudo journalctl -u career-ops-backend -f`
- [ ] Check disk space: `df -h`
- [ ] Review GitHub Actions history for failed deployments
- [ ] Update dependencies monthly: `uv lock --upgrade`
- [ ] Rotate secrets quarterly

### Troubleshooting Commands
```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Check service status
sudo systemctl status career-ops-backend

# View recent logs
sudo journalctl -u career-ops-backend -n 50 --no-pager

# Restart service
sudo systemctl restart career-ops-backend

# Check if port is listening
sudo netstat -tlnp | grep 8000

# Test locally on VM
curl http://localhost:8000/health

# Check disk usage
df -h

# Check memory usage
free -h

# Check running processes
ps aux | grep uvicorn
```

## Rollback Procedure

If deployment fails:

1. SSH to VM: `gcloud compute ssh career-ops-backend --zone=us-central1-a`
2. Check service status: `sudo systemctl status career-ops-backend`
3. View logs: `sudo journalctl -u career-ops-backend -n 100 --no-pager`
4. Rollback to previous version:
   ```bash
   cd /opt/career-ops-backend
   git log --oneline -5  # Find previous commit
   git reset --hard PREVIOUS_COMMIT_SHA
   cd backend
   ~/.cargo/bin/uv sync
   sudo systemctl restart career-ops-backend
   ```

## Success Criteria

✅ VM is running and accessible  
✅ Service starts automatically on boot  
✅ Health endpoint returns 200 OK  
✅ API endpoints work with valid API key  
✅ GitHub Actions deploys successfully on push to main  
✅ Logs are accessible and informative  
✅ Environment variables are properly configured  
✅ No secrets committed to repository  

## Support Resources

- GCP Documentation: https://cloud.google.com/docs
- GitHub Actions Docs: https://docs.github.com/actions
- FastAPI Deployment: https://fastapi.tiangolo.com/deployment/
- uv Documentation: https://docs.astral.sh/uv/

---

**Date Completed**: _______________  
**Deployed By**: _______________  
**VM IP**: _______________  
**API Endpoint**: _______________

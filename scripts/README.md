# Deployment Scripts

This directory contains automation scripts for deploying the Career Ops backend.

## Scripts

### `setup-vm.sh`
**Purpose**: Initial VM configuration (run once)  
**Where**: On the GCP VM (via SSH)  
**When**: After creating a new VM for the first time

**Usage**:
```bash
# Method 1: Copy and run on VM
gcloud compute ssh career-ops-backend --zone=us-central1-a
# Then paste the script contents

# Method 2: Run from local machine
gcloud compute ssh career-ops-backend --zone=us-central1-a < scripts/setup-vm.sh
```

**What it does**:
- Installs system dependencies (git, nginx, etc.)
- Installs uv (Python package manager)
- Clones your repository
- Creates `.env` file template
- Installs Python dependencies
- Sets up systemd service
- Configures nginx reverse proxy
- Starts the service

### `deploy.sh`
**Purpose**: Manual deployment to VM  
**Where**: On your local machine  
**When**: When you want to manually deploy instead of using GitHub Actions

**Usage**:
```bash
./scripts/deploy.sh
```

**What it does**:
- Connects to your GCP VM
- Pulls latest code from git
- Installs/updates dependencies
- Restarts the service
- Runs health check
- Reports deployment status

**Requirements**:
- `gcloud` CLI authenticated
- SSH access to the VM
- Git repository already cloned on VM (setup-vm.sh must have run first)

## Permissions

Both scripts are executable:
```bash
chmod +x scripts/setup-vm.sh
chmod +x scripts/deploy.sh
```

## Configuration

These scripts use the following defaults:
- **VM Name**: `career-ops-backend`
- **Zone**: `us-central1-a`
- **App Directory**: `/opt/career-ops-backend`
- **Service Port**: `8000`

To change these, edit the variables at the top of each script.

## Troubleshooting

### setup-vm.sh fails
- Ensure you have SSH access to the VM
- Check that the VM is Ubuntu 22.04 LTS
- Verify you have sudo permissions on the VM

### deploy.sh fails
- Ensure `gcloud` is authenticated: `gcloud auth login`
- Verify the VM name and zone are correct
- Check that setup-vm.sh has been run successfully first
- Verify you have git configured on the VM

## See Also

- `../QUICKSTART-DEPLOY.md` - Complete deployment guide
- `../DEPLOYMENT.md` - Detailed documentation
- `../.github/workflows/deploy.yml` - GitHub Actions workflow

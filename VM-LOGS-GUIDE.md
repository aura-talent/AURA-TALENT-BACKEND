# VM Logs Guide

## Quick Commands to Check Logs

### 1. View Recent Logs (Last 50 lines)
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend -n 50 --no-pager"
```

### 2. View Live Logs (Real-time, Press Ctrl+C to exit)
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Then run:
sudo journalctl -u career-ops-backend -f
```

### 3. View Last 100 Lines
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend -n 100 --no-pager"
```

### 4. View Errors Only
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend -p err -n 50 --no-pager"
```

### 5. View Logs Since Specific Time
```bash
# Logs from last hour
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend --since '1 hour ago' --no-pager"

# Logs from today
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend --since today --no-pager"
```

### 6. Check Service Status
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo systemctl status career-ops-backend"
```

### 7. Search for Specific Error
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend | grep -i 'error\|exception\|failed'"
```

## Common Log Patterns

### Successful Startup
```
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### API Request
```
INFO:     127.0.0.1:xxxxx - "GET /health HTTP/1.1" 200 OK
INFO:     127.0.0.1:xxxxx - "POST /api/v1/jobs/evaluate HTTP/1.1" 200 OK
```

### Errors to Watch For
- `PermissionDenied` - Authentication/authorization issues
- `ImportError` - Missing dependencies
- `Connection refused` - Service can't connect to external APIs
- `ModuleNotFoundError` - Python package not installed

## Troubleshooting Common Issues

### Issue: Service Won't Start
```bash
# Check detailed status
sudo systemctl status career-ops-backend -l

# View recent errors
sudo journalctl -u career-ops-backend -n 50 --no-pager
```

### Issue: Import Errors
```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Check if dependencies are installed
cd /opt/career-ops-backend
~/.local/bin/uv pip list

# Reinstall dependencies
~/.local/bin/uv sync

# Restart service
sudo systemctl restart career-ops-backend
```

### Issue: Permission Errors
```bash
# Check file ownership
ls -la /opt/career-ops-backend

# Fix if needed
sudo chown -R charleshor:charleshor /opt/career-ops-backend
sudo systemctl restart career-ops-backend
```

## Advanced Log Analysis

### Export Logs to File
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend --since today --no-pager" > logs.txt
```

### Search Logs from Local Machine
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend --no-pager" | grep "ERROR"
```

### Monitor Multiple Log Sources
```bash
# SSH to VM first
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Then run multiple tail commands
sudo journalctl -u career-ops-backend -f &  # Service logs
tail -f /var/log/nginx/access.log &          # Nginx access
tail -f /var/log/nginx/error.log             # Nginx errors
```

## Quick Health Checks

### 1. Is the service running?
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo systemctl is-active career-ops-backend"
# Should return: active
```

### 2. When did it last restart?
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo systemctl show career-ops-backend | grep ActiveEnterTimestamp"
```

### 3. What's the memory usage?
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo systemctl status career-ops-backend | grep Memory"
```

### 4. Test API from VM
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="curl -s http://localhost:8000/health"
```

## Log Shortcuts

Add these to your local `.bashrc` or `.zshrc` for quick access:

```bash
# Add to ~/.bashrc or ~/.zshrc
alias vm-logs="gcloud compute ssh career-ops-backend --zone=us-central1-a --command='sudo journalctl -u career-ops-backend -n 50 --no-pager'"
alias vm-logs-live="gcloud compute ssh career-ops-backend --zone=us-central1-a --command='sudo journalctl -u career-ops-backend -f'"
alias vm-status="gcloud compute ssh career-ops-backend --zone=us-central1-a --command='sudo systemctl status career-ops-backend'"
alias vm-restart="gcloud compute ssh career-ops-backend --zone=us-central1-a --command='sudo systemctl restart career-ops-backend'"
alias vm-ssh="gcloud compute ssh career-ops-backend --zone=us-central1-a"
```

Then reload:
```bash
source ~/.bashrc  # or source ~/.zshrc
```

Now you can use:
```bash
vm-logs        # View recent logs
vm-logs-live   # View live logs
vm-status      # Check status
vm-restart     # Restart service
vm-ssh         # SSH to VM
```

# Current Deployment Information

## ✅ Live API

**Base URL**: `http://35.253.164.188:8000`

⚠️ **IP Changed** - The VM IP changed from `34.132.193.54` to `35.253.164.188` after we fixed the Vertex AI authentication scopes.

## API Endpoints

- **Health Check**: http://35.253.164.188:8000/health
- **API Docs**: http://35.253.164.188:8000/docs
- **API Base**: http://35.253.164.188:8000/api/v1

## Configuration

- **Model**: `google_vertexai:gemini-2.5-flash`
- **Authentication**: `X-API-Key: AURA_TALENT_88#`
- **CORS**: Open to all origins (*)
- **VM Name**: `career-ops-backend`
- **VM Zone**: `us-central1-a`
- **Project**: `project-959ef152-d27b-437b-acc`

## Frontend Configuration

Update your frontend `.env` files with the new IP:

```bash
# React / Next.js (.env.local)
NEXT_PUBLIC_API_URL=http://35.253.164.188:8000
NEXT_PUBLIC_API_KEY=AURA_TALENT_88#
```

## Testing

```bash
# Health check
curl http://35.253.164.188:8000/health

# With authentication
curl -H "X-API-Key: AURA_TALENT_88#" http://35.253.164.188:8000/api/v1/resume/text
```

## What Changed

### Issue Fixed
The VM didn't have the correct authentication scopes for Vertex AI, causing this error:
```
ACCESS_TOKEN_SCOPE_INSUFFICIENT
```

### Solution Applied
1. Stopped the VM
2. Updated service account scopes to include full `cloud-platform` access
3. Restarted the VM
4. VM received new IP: `35.253.164.188`

### Side Effect
⚠️ **IP address changed!** You need to update:
1. Your frontend environment variables
2. Any hardcoded API URLs
3. Firewall rules or allow-lists

## Checking Logs

See `VM-LOGS-GUIDE.md` for detailed instructions.

**Quick command**:
```bash
gcloud compute ssh career-ops-backend --zone=us-central1-a --command="sudo journalctl -u career-ops-backend -n 50 --no-pager"
```

## Management Commands

```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# View logs
sudo journalctl -u career-ops-backend -n 50 --no-pager

# Restart service
sudo systemctl restart career-ops-backend

# Check status
sudo systemctl status career-ops-backend
```

---

**Last Updated**: June 11, 2026  
**Current IP**: 35.253.164.188  
**Status**: ✅ Running with Vertex AI properly configured

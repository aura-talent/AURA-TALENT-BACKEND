# GitHub Secrets Setup

Go to: `https://github.com/aura-talent/AURA-TALENT-BACKEND/settings/secrets/actions/new`

## Required Secrets

### 1. GCP_PROJECT_ID
```
project-959ef152-d27b-437b-acc
```

### 2. GCP_VM_ZONE
```
us-central1-a
```

### 3. GCP_VM_NAME
```
career-ops-backend
```

### 4. GCP_SSH_PRIVATE_KEY
```
-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACD2T1NLRlmK7M6uzutZo42OU3k68sYYLvl3Rr6vBabYxQAAAJgPvDAsD7ww
LAAAAAtzc2gtZWQyNTUxOQAAACD2T1NLRlmK7M6uzutZo42OU3k68sYYLvl3Rr6vBabYxQ
AAAEDAZL04gnh+Z3ij3eriQn1F1f3dna4UG54S318dLOhZsfZPU0tGWYrszq7O61mjjY5T
eTryxhgu+XdGvq8FptjFAAAADmdpdGh1Yi1hY3Rpb25zAQIDBAUGBw==
-----END OPENSSH PRIVATE KEY-----
```

### 5. BACKEND_API_KEY
```
AURA_TALENT_88#
```

### 6. ANTHROPIC_API_KEY
**Not needed** - We're using Vertex AI which authenticates via the VM's service account.

---

## How to Add Secrets

1. Go to: https://github.com/aura-talent/AURA-TALENT-BACKEND/settings/secrets/actions
2. Click "New repository secret"
3. For each secret:
   - Name: Enter the exact name above (case-sensitive)
   - Value: Copy and paste the value
   - Click "Add secret"

---

## Verification

After adding all secrets, they should appear in the secrets list:
- ✅ GCP_PROJECT_ID
- ✅ GCP_VM_ZONE  
- ✅ GCP_VM_NAME
- ✅ GCP_SSH_PRIVATE_KEY
- ✅ BACKEND_API_KEY
- ✅ ANTHROPIC_API_KEY

---

## Test Auto-Deploy

Once secrets are added:

```bash
# Make a test change
echo "# Test deployment" >> README.md

# Commit and push
git add .
git commit -m "Test auto-deployment"
git push origin main
```

Watch the deployment at:
https://github.com/aura-talent/AURA-TALENT-BACKEND/actions

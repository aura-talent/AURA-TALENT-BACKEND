# Frontend Integration Guide

## API Configuration

### Base URL
```
http://34.132.193.54:8000
```

### Authentication Header
All API requests **must** include this header:

```
X-API-Key: AURA_TALENT_88#
```

## Frontend Environment Variables

### React / Next.js (.env.local)
```bash
NEXT_PUBLIC_API_URL=http://34.132.193.54:8000
NEXT_PUBLIC_API_KEY=AURA_TALENT_88#
```

### Vue.js (.env)
```bash
VUE_APP_API_URL=http://34.132.193.54:8000
VUE_APP_API_KEY=AURA_TALENT_88#
```

### Vanilla JavaScript
```javascript
const API_URL = 'http://34.132.193.54:8000';
const API_KEY = 'AURA_TALENT_88#';
```

## Example API Calls

### JavaScript (Fetch API)
```javascript
const API_URL = 'http://34.132.193.54:8000';
const API_KEY = 'AURA_TALENT_88#';

// Health check
async function checkHealth() {
  const response = await fetch(`${API_URL}/health`, {
    headers: {
      'X-API-Key': API_KEY
    }
  });
  return await response.json();
}

// Upload resume (text)
async function uploadResumeText(userId, resumeText) {
  const response = await fetch(`${API_URL}/api/v1/resume/text`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY
    },
    body: JSON.stringify({
      user_id: userId,
      text: resumeText
    })
  });
  return await response.json();
}

// Upload resume (file)
async function uploadResumeFile(userId, file) {
  const formData = new FormData();
  formData.append('user_id', userId);
  formData.append('file', file);

  const response = await fetch(`${API_URL}/api/v1/resume/upload`, {
    method: 'POST',
    headers: {
      'X-API-Key': API_KEY
    },
    body: formData
  });
  return await response.json();
}

// Evaluate job
async function evaluateJob(userId, jdUrl, jdText = null) {
  const response = await fetch(`${API_URL}/api/v1/jobs/evaluate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY
    },
    body: JSON.stringify({
      user_id: userId,
      jd_url: jdUrl,
      jd_text: jdText
    })
  });
  return await response.json();
}
```

### React Hooks Example
```javascript
import { useState, useEffect } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL;
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

function useCareerOpsAPI() {
  const headers = {
    'Content-Type': 'application/json',
    'X-API-Key': API_KEY
  };

  const uploadResumeText = async (userId, text) => {
    const response = await fetch(`${API_URL}/api/v1/resume/text`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ user_id: userId, text })
    });
    if (!response.ok) throw new Error('Upload failed');
    return response.json();
  };

  const evaluateJob = async (userId, jdUrl, jdText = null) => {
    const response = await fetch(`${API_URL}/api/v1/jobs/evaluate`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ user_id: userId, jd_url: jdUrl, jd_text: jdText })
    });
    if (!response.ok) throw new Error('Evaluation failed');
    return response.json();
  };

  return { uploadResumeText, evaluateJob };
}

export default useCareerOpsAPI;
```

### Axios Example
```javascript
import axios from 'axios';

const api = axios.create({
  baseURL: 'http://34.132.193.54:8000',
  headers: {
    'X-API-Key': 'AURA_TALENT_88#'
  }
});

// Upload resume
const uploadResume = async (userId, resumeText) => {
  const response = await api.post('/api/v1/resume/text', {
    user_id: userId,
    text: resumeText
  });
  return response.data;
};

// Evaluate job
const evaluateJob = async (userId, jdUrl) => {
  const response = await api.post('/api/v1/jobs/evaluate', {
    user_id: userId,
    jd_url: jdUrl
  });
  return response.data;
};

export { uploadResume, evaluateJob };
```

## API Endpoints

### Health Check (Public - No Auth Required)
```
GET /health
```

### Resume Management
```
POST /api/v1/resume/upload       # Upload PDF/DOCX/TXT/MD file
POST /api/v1/resume/text         # Upload resume as text
GET  /api/v1/resume/{user_id}    # Get stored resume
POST /api/v1/resume/suggestions  # Get JD-specific suggestions
```

### Job Evaluation
```
POST /api/v1/jobs/evaluate       # Evaluate a job posting
POST /api/v1/jobs/compare        # Compare multiple offers
```

### Job Scanning
```
POST /api/v1/scan                # Scan job boards (Greenhouse, Ashby, Lever)
```

### Applications Tracker
```
GET   /api/v1/applications/{user_id}           # List applications
GET   /api/v1/applications/{user_id}/{id}/report   # Get evaluation report
PATCH /api/v1/applications/{user_id}/{id}/status  # Update status
```

## Security Best Practices

### ⚠️ Important: Never Expose API Key in Frontend Code

**Bad (Don't do this):**
```javascript
// ❌ Hardcoded in frontend code
const API_KEY = 'AURA_TALENT_88#';  // This is visible to anyone!
```

**Good (Do this):**
```javascript
// ✅ Use environment variables
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;  // Hidden from source code
```

### For Production:
1. **Use environment variables** - Never commit API keys to git
2. **Use HTTPS** - Set up SSL certificate (Let's Encrypt)
3. **Implement user authentication** - Replace shared key with JWT/OAuth
4. **Rate limiting** - Add rate limits per user
5. **CORS restrictions** - Limit to your frontend domain only

## CORS Configuration

Currently set to allow all origins (`*`). For production, update the VM's `.env` file:

```bash
# SSH to VM
gcloud compute ssh career-ops-backend --zone=us-central1-a

# Edit .env
nano /opt/career-ops-backend/.env

# Change CORS_ORIGINS to your frontend URL
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com

# Restart service
sudo systemctl restart career-ops-backend
```

## Testing with cURL

```bash
# Health check (no auth needed)
curl http://34.132.193.54:8000/health

# Upload resume text
curl -X POST http://34.132.193.54:8000/api/v1/resume/text \
  -H "X-API-Key: AURA_TALENT_88#" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "text": "Software Engineer with 5 years of experience..."
  }'

# Evaluate job
curl -X POST http://34.132.193.54:8000/api/v1/jobs/evaluate \
  -H "X-API-Key: AURA_TALENT_88#" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "jd_url": "https://boards.greenhouse.io/anthropic/jobs/..."
  }'
```

## API Documentation

Interactive API documentation (Swagger UI):
```
http://34.132.193.54:8000/docs
```

## Error Handling

```javascript
async function callAPI() {
  try {
    const response = await fetch(`${API_URL}/api/v1/jobs/evaluate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY
      },
      body: JSON.stringify(data)
    });

    if (!response.ok) {
      if (response.status === 401) {
        throw new Error('Invalid API key');
      } else if (response.status === 422) {
        const error = await response.json();
        throw new Error(`Validation error: ${JSON.stringify(error)}`);
      } else {
        throw new Error(`HTTP error: ${response.status}`);
      }
    }

    return await response.json();
  } catch (error) {
    console.error('API call failed:', error);
    throw error;
  }
}
```

## Quick Start for Frontend Developers

1. **Set environment variable**:
   - Create `.env.local` (Next.js/React) or `.env` (Vue)
   - Add `NEXT_PUBLIC_API_KEY=AURA_TALENT_88#`
   - Add `NEXT_PUBLIC_API_URL=http://34.132.193.54:8000`

2. **Add authentication header to all API calls**:
   ```javascript
   headers: {
     'X-API-Key': process.env.NEXT_PUBLIC_API_KEY
   }
   ```

3. **Test with the health endpoint first**:
   ```javascript
   fetch('http://34.132.193.54:8000/health')
     .then(r => r.json())
     .then(console.log);
   ```

4. **Check API docs for request/response schemas**:
   - Visit: http://34.132.193.54:8000/docs

---

**Need help?** Check the API docs at http://34.132.193.54:8000/docs or review the examples above.

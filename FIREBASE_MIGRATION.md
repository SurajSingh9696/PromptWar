# VoteWise India — Firebase Migration Documentation

## Architecture Overview

```
Before (Cloud Run)                  After (Firebase)
─────────────────────               ─────────────────────────────────
User Browser                        User Browser
    │                                   │
    ▼                                   ▼
Cloud Run (Docker)                  Firebase Hosting (CDN)
  ├── FastAPI (Python)                  │ (static/ files served globally)
  │    ├── /chat → Gemini API           │
  │    ├── /eligibility                 ├─── /chat ─────────────────┐
  │    ├── /timeline                    ├─── /eligibility           ├── Cloud Functions (Gen 2)
  │    └── /states                      ├─── /timeline              │   ├── auth.verify_id_token()
  └── static/ (bundled in image)       └─── /states ───────────────┘   ├── Firestore (rate_limits)
                                                                        ├── Firestore (cache)
                                                                        ├── Firestore (analytics)
                                                                        └── Vertex AI Gemini
```

---

## Google Services Added (8 total)

| # | Service | Role |
|---|---------|------|
| 1 | Firebase Hosting | Serves frontend via global CDN with HTTPS |
| 2 | Firebase Cloud Functions (Gen 2) | Serverless Python API replaces FastAPI |
| 3 | Cloud Firestore | Response cache + analytics + rate limiting |
| 4 | Firebase Auth (Anonymous) | Session identity and rate limiting |
| 5 | Vertex AI Gemini | AI inference (replaces direct API key call) |
| 6 | Firebase Analytics | question_asked events per query |
| 7 | Firebase Performance Monitoring | chat_request trace per API call |
| 8 | Firebase Remote Config | Toggle model/cache without redeploy |

---

## Setup & Deployment Steps

### Step 1: Firebase Login (Manual — requires browser)

Open a new PowerShell window and run:

```powershell
npx firebase-tools login
```

Sign in with your Google account in the browser that opens.

### Step 2: Create or Select a Firebase Project

```powershell
# List existing projects
npx firebase-tools projects:list

# OR create a new project
npx firebase-tools projects:create voter-assistant-india
```

Then update `.firebaserc` with your actual project ID:
```json
{
  "projects": {
    "default": "YOUR-ACTUAL-PROJECT-ID"
  }
}
```

### Step 3: Enable Required Services in Firebase Console

Go to console.firebase.google.com → your project:

1. Authentication → Sign-in method → Enable Anonymous
2. Firestore Database → Create database → Choose asia-south1 (Mumbai) → Start in production mode
3. Analytics → Enable Google Analytics (linked to a GA4 property)

> IMPORTANT: Firebase must be on the Blaze (pay-as-you-go) plan for Cloud Functions Gen 2. Upgrade at: Firebase Console → Settings → Usage and billing.

### Step 4: Enable Vertex AI

```powershell
gcloud services enable aiplatform.googleapis.com --project=YOUR-PROJECT-ID
```

### Step 5: Set Remote Config Parameters

In Firebase Console → Remote Config → Add parameters:

| Key | Default Value | Type |
|-----|--------------|------|
| active_model | gemini-2.5-flash-lite-preview-06-17 | String |
| enable_cache | true | Boolean |

### Step 6: Deploy

```powershell
cd x:\voter_assistant

# Deploy Firestore rules + indexes
npx firebase-tools deploy --only firestore

# Deploy Cloud Functions (3-5 min first time)
npx firebase-tools deploy --only functions

# Deploy Frontend to Hosting
npx firebase-tools deploy --only hosting

# Or deploy everything at once
npx firebase-tools deploy
```

---

## File Structure After Migration

```
voter_assistant/
├── firebase.json              ← Firebase config (Hosting + Functions)
├── .firebaserc                ← Project alias
├── firestore.rules            ← Firestore security rules
├── firestore.indexes.json     ← Composite indexes
│
├── functions/                 ← Cloud Functions (replaces app/)
│   ├── __init__.py
│   ├── main.py                ← 5 HTTPS function endpoints
│   ├── gemini_client.py       ← Vertex AI SDK (no API key needed)
│   ├── rules_engine.py        ← Unchanged business logic
│   ├── prompts.py             ← Unchanged
│   ├── models.py              ← Unchanged
│   ├── requirements.txt       ← Firebase + Vertex AI deps
│   └── data/
│       └── election_data.json
│
├── static/                    ← Served by Firebase Hosting
│   ├── index.html             ← Added Firebase SDK script tag
│   ├── firebase-init.js       ← NEW: Firebase init module
│   ├── app.js                 ← Added auth + analytics + perf
│   └── style.css              ← Unchanged
│
├── app/                       ← DEPRECATED (kept for reference)
├── Dockerfile                 ← DEPRECATED (no longer used)
└── tests/                     ← Still valid for function logic
```

---

## Firestore Data Schema

### /analytics/chats/entries/{auto-id}
```json
{
  "session_id":       "firebase-anonymous-uid",
  "message":          "How do I register to vote?",
  "reply_source":     "local | cache | ai",
  "state":            "DL",
  "language":         "Hindi",
  "timestamp":        "Firestore ServerTimestamp",
  "response_time_ms": 142
}
```

### /cache/{sha256-hash}
```json
{
  "query":               "how do i register to vote",
  "reply":               "Voter Registration in India...",
  "suggested_followups": ["What documents for Form 6?"],
  "source":              "ai",
  "created_at":          1746000000.0,
  "hit_count":           14
}
```

### /rate_limits/{uid}
```json
{
  "window_start": 1746000000.0,
  "count":        12
}
```

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| Transport | HTTPS enforced by Firebase Hosting (HSTS) |
| Identity | Anonymous Firebase Auth (every user gets a UID) |
| Rate Limiting | 30 requests/hour per UID via Firestore transaction |
| Firestore | All collections locked — admin SDK writes only |
| Credentials | Vertex AI uses ADC — no API keys in code |
| Headers | X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| Partisan Guard | Keyword filter before any AI call |

---

## What Changed vs Original

### Backend
| Feature | Before | After |
|---------|--------|-------|
| Framework | FastAPI | Firebase Cloud Functions |
| Auth | None | Firebase Anonymous Auth |
| Rate limiting | None | Firestore (30 req/hr/user) |
| Analytics | None | Firestore analytics collection |
| Response cache | Client sessionStorage | Firestore (server-side, shared) |
| Deployment | Docker → Cloud Run | firebase deploy |

### AI Client
| Feature | Before | After |
|---------|--------|-------|
| SDK | google-genai (API key) | google-cloud-aiplatform (ADC) |
| Auth | GEMINI_API_KEY env var | Service Account ADC (automatic) |
| Cache | None | Firestore 24-hour cache |

### Frontend
| Feature | Before | After |
|---------|--------|-------|
| API calls | No auth headers | Authorization: Bearer token |
| Analytics | None | Firebase Analytics events |
| Performance | None | Firebase Performance traces |
| Config | Hardcoded model names | Firebase Remote Config |

---

## Environment Variables

These are automatically injected in Cloud Functions — no manual setup needed:

| Variable | Source |
|----------|--------|
| GCLOUD_PROJECT | Auto-injected by Firebase |
| GOOGLE_CLOUD_PROJECT | Auto-injected |
| VERTEX_REGION | Set in firebase.json |

The old GEMINI_API_KEY is no longer required.

---

## Future Improvements (Score Maximization)

1. Firebase App Check — Add reCAPTCHA v3 attestation to prevent bot abuse
2. Cloud Tasks — Queue heavy Gemini calls asynchronously
3. BigQuery Export — Enable Firestore to BigQuery sync for advanced analytics
4. Firebase Extensions — "Translate Text in Firestore" for multilingual cache
5. Secret Manager — Store any future API keys in GCP Secret Manager
6. Cloud Monitoring Dashboards — Custom metrics for query volume and latency
7. Firebase Test Lab — Run frontend Robo Tests for automated UI testing

---

## Verifying the Deployment

```bash
# Test health endpoint
curl https://YOUR-PROJECT-ID.web.app/health
# Expected: {"status": "ok", "backend": "firebase-functions"}

# Test states endpoint (no auth required)
curl https://YOUR-PROJECT-ID.web.app/states
```

Note: /chat and /eligibility require a Firebase Auth token.
Use the browser frontend which handles auth automatically.

# VoteWise India

Non-partisan election process assistant for India.  
This version is **standalone**: no Firebase dependency. It uses:

- **Flask** backend (`functions/main.py`)
- **Gemini API key** (`GEMINI_API_KEY`)
- **Cloud Run** deployment (`gcloud run deploy`)
- Static frontend served by the same service (`/static` + SPA fallback)

## Features

- Chat assistant for election process education
- Deterministic local answers for common voter questions
- Rules engine for eligibility and state timelines
- Gemini fallback for complex queries
- 22-language UI support

## API Endpoints

- `POST /chat`
- `GET /eligibility?age=...&citizen=...&state=...`
- `GET /timeline?state=DL`
- `GET /states`
- `GET /health`

## Local Run

### 1. Install dependencies

```powershell
pip install -r functions\requirements.txt -r requirements-test.txt
```

### 2. Set Gemini API key

```powershell
$env:GEMINI_API_KEY="your_api_key_here"
```

### 3. Run backend

```powershell
$env:PYTHONPATH="."
python -m functions.main
```

App runs on `http://localhost:8080`.

## Testing

```powershell
$env:PYTHONPATH="."
pytest tests\ -v
```

## Deploy to Cloud Run

### Option A: One-command script

```powershell
.\deploy-cloudrun.ps1 -ProjectId YOUR_GCP_PROJECT_ID -GeminiApiKey "YOUR_GEMINI_API_KEY"
```

Optional:

```powershell
.\deploy-cloudrun.ps1 -ProjectId YOUR_GCP_PROJECT_ID -SkipTests
```

### Option B: Manual deploy

```powershell
gcloud config set project YOUR_GCP_PROJECT_ID
gcloud run deploy votewise-india --region asia-south1 --source . --allow-unauthenticated --set-env-vars GEMINI_API_KEY=YOUR_GEMINI_API_KEY,ACTIVE_MODEL=gemini-2.5-flash
```

## Environment Variables

- `GEMINI_API_KEY` (required)
- `ACTIVE_MODEL` (optional, default: `gemini-2.5-flash`)
- `FALLBACK_MODEL` (optional, default: `gemini-1.5-flash`)

## Project Structure

```text
voter_assistant/
├── functions/
│   ├── main.py
│   ├── gemini_client.py
│   ├── rules_engine.py
│   ├── prompts.py
│   ├── models.py
│   ├── requirements.txt
│   └── data/election_data.json
├── static/
│   ├── index.html
│   ├── app.js
│   └── style.css
├── tests/
├── Dockerfile
└── deploy-cloudrun.ps1
```
# PromptWar

# Resume Match Scorer — GCP Cloud Project

**Live URL:** https://resume-checker-927376439125.us-central1.run.app  
**GCP Project ID:** `resume-checker-1775416523`

---

## 1. What is this project?

Resume Match Scorer is a web application that helps job seekers understand how well their resume aligns with a specific job description. A user uploads their PDF resume, pastes a job description, and receives:

- A **match score** (0–100%) showing what percentage of the job's required skills appear in the resume
- A list of **matched skills** (green) the resume already covers
- A list of **missing skills** (red) the user could add to improve their chances
- A full list of every technical skill detected in the resume

The application is fully serverless — there are no servers to manage. Everything runs on Google Cloud managed services.

---

## 2. Cloud Services Used

| # | Service | Role |
|---|---------|------|
| 1 | **Cloud Storage (GCS)** | Stores uploaded PDF resumes in the `resume-checker-1775416523-resume-uploads` bucket |
| 2 | **Cloud Functions (2nd gen)** | Event-driven function that fires whenever a new PDF lands in the bucket; extracts text and writes results to Firestore |
| 3 | **Cloud Firestore** | NoSQL database that holds parsed resume data (skills, entities, raw text); polled by the web app to check parse status |
| 4 | **Cloud Run** | Hosts the Flask web application; publicly accessible, scales to zero when idle |
| *(supporting)* | **Natural Language API** | Called inside the Cloud Function to identify named entities (organizations, job titles) in the resume text |
| *(supporting)* | **Cloud Build** | Used to build and push the Docker image for Cloud Run |

> **Note:** Logging, Cloud Shell, and IAM are not counted as project services.

---

## 3. How the Services Interact

```
Browser
  │
  │  POST /upload (PDF file)
  ▼
Cloud Run  ──── uploads PDF ────►  Cloud Storage
(Flask app)                         (resume-uploads bucket)
  │                                       │
  │  GET /status/<id> (polling)           │ object.finalized event
  │                                       ▼
  │                               Cloud Functions
  │                               (resume_parser)
  │                                 │  1. Download PDF bytes from GCS
  │                                 │  2. Extract text via PyMuPDF
  │                                 │  3. Call Natural Language API
  │                                 │  4. Regex scan for 30+ tech skills
  │                                 │  5. Write results to Firestore
  │                                       │
  │  ◄─── document appears ───────────────┘
  │         (status: ready)
  │
  │  POST /score (job description)
  │   Reads skills from Firestore,
  │   compares with job description,
  │   returns match % + breakdown
  ▼
Browser renders score, matched skills, missing skills
```

**Step-by-step data flow:**

1. The user selects a PDF in the browser and clicks *Upload & Parse*.
2. The Flask app (Cloud Run) receives the file and writes it to the GCS bucket under `resumes/<uuid>.pdf`.
3. The GCS `object.finalized` event triggers the **Cloud Function** (`resume_parser`).
4. The Cloud Function downloads the PDF from GCS, extracts plain text using PyMuPDF, sends the text to the **Natural Language API** for entity recognition, and scans for known tech skills using a regex.
5. Results are written to a **Firestore** document (`resumes` collection, document ID `resumes_<uuid>`).
6. The browser polls `/status/<uuid>` every 4 seconds. Once the Firestore document exists, the app shows Step 2.
7. The user pastes a job description and clicks *Get Match Score*.
8. The Flask app reads the resume skills from Firestore, extracts skills from the job description using the same regex, and computes the match percentage.
9. Results are rendered in the browser with color-coded chips.

---

## 4. Setup / Install / Run

### Prerequisites

- A Google Cloud project with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- Docker (only needed for local builds; Cloud Build is used for deployment)

### One-time GCP setup

```bash
PROJECT="resume-checker-1775416523"

# Enable required APIs
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  language.googleapis.com \
  cloudbuild.googleapis.com \
  --project="$PROJECT"

# Create the GCS bucket
gsutil mb -p "$PROJECT" -l us-central1 \
  gs://${PROJECT}-resume-uploads

# Create Firestore database (native mode)
gcloud firestore databases create \
  --project="$PROJECT" \
  --location=us-central1
```

### Deploy the Cloud Function

```bash
cd cloud_function
gcloud functions deploy resume_parser \
  --project="$PROJECT" \
  --region=us-central1 \
  --gen2 \
  --runtime=python312 \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${PROJECT}-resume-uploads" \
  --source=. \
  --entry-point=resume_parser \
  --memory=512MB \
  --timeout=120s
```

### Deploy the Web App to Cloud Run

```bash
cd appengine

# Build and push the Docker image
gcloud builds submit \
  --tag gcr.io/$PROJECT/resume-checker \
  --project="$PROJECT" .

# Deploy to Cloud Run (publicly accessible)
gcloud run deploy resume-checker \
  --image gcr.io/$PROJECT/resume-checker \
  --project="$PROJECT" \
  --region=us-central1 \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$PROJECT \
  --memory=512Mi
```

The final line of output will print the public **Service URL**.

### Run locally (development)

```bash
cd appengine
pip install -r requirements.txt

# Authenticate as yourself so the app can reach GCS and Firestore
gcloud auth application-default login

GOOGLE_CLOUD_PROJECT=resume-checker-1775416523 python main.py
# Visit http://localhost:8080
```

> **Note:** Local runs still read/write the live GCS bucket and Firestore, so uploads will trigger the real Cloud Function.

---

## Project Structure

```
ResumeCheck/
├── README.md                   ← this file
├── cloud_function/
│   ├── main.py                 ← Cloud Function source (PDF parser)
│   ├── requirements.txt
│   └── cloudbuild_deploy.sh    ← convenience deploy script
└── appengine/                  ← Flask web app (deployed to Cloud Run)
    ├── main.py                 ← Flask routes (upload, status, score)
    ├── requirements.txt
    ├── Dockerfile
    ├── app.yaml                ← App Engine config (kept for reference)
    ├── deploy.sh               ← Cloud Run deploy script
    └── templates/
        └── index.html          ← single-page UI
```

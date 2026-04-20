#!/usr/bin/env bash
# Run from cloud_function/ directory after billing is enabled.
set -euo pipefail

PROJECT="resume-checker-1775416523"
BUCKET="${PROJECT}-resume-uploads"
REGION="us-central1"

echo "==> Creating GCS bucket: gs://${BUCKET}"
gsutil mb -p "$PROJECT" -l "$REGION" "gs://${BUCKET}" || echo "Bucket already exists."

echo "==> Enabling Firestore (native mode)"
gcloud firestore databases create --project="$PROJECT" --location="$REGION" || echo "Firestore already initialized."

echo "==> Deploying Cloud Function"
gcloud functions deploy resume_parser \
  --project="$PROJECT" \
  --region="$REGION" \
  --gen2 \
  --runtime=python312 \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${BUCKET}" \
  --source=. \
  --entry-point=resume_parser \
  --memory=512MB \
  --timeout=120s

echo "==> Done. Upload a PDF to gs://${BUCKET}/resumes/<file>.pdf to test."

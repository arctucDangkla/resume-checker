#!/usr/bin/env bash
# Run from appengine/ directory after billing is enabled.
set -euo pipefail

PROJECT="resume-checker-1775416523"

echo "==> Initializing App Engine (one-time)"
gcloud app create --project="$PROJECT" --region=us-central || echo "App Engine already initialized."

echo "==> Deploying App Engine app"
gcloud app deploy app.yaml --project="$PROJECT" --quiet

echo "==> App URL:"
gcloud app browse --project="$PROJECT" --no-launch-browser

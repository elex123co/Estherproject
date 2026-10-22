#!/bin/sh
# Container entrypoint. Builds a clearly-labelled DEMO model on first start if none exists, then serves Viona.
set -e
cd /app/backend
if [ ! -f /app/models/intrusion_model.joblib ]; then
  echo "No trained model found: training the synthetic demo model (flagged as synthetic in the UI)."
  python scripts/generate_synthetic_data.py
  python scripts/train.py --data ../data/synthetic --synthetic --dataset-name synthetic-smoke-test
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

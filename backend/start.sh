#!/bin/sh
# Container entrypoint. Builds a clearly-labelled DEMO model on first start if none exists, then serves Viona.
set -e
# Hosts such as Render allow one persistent disk per service. Point VIONA_STORAGE at it and both folders live inside it.
if [ -n "$VIONA_STORAGE" ]; then
  mkdir -p "$VIONA_STORAGE/data" "$VIONA_STORAGE/models"
  rm -rf /app/data /app/models
  ln -s "$VIONA_STORAGE/data" /app/data
  ln -s "$VIONA_STORAGE/models" /app/models
fi
cd /app/backend
if [ ! -f /app/models/intrusion_model.joblib ] && [ -f /app/demo_model/intrusion_model.joblib ]; then
  echo "No trained model found: installing the bundled synthetic demo model (flagged as synthetic in the UI)."
  mkdir -p /app/models
  cp /app/demo_model/* /app/models/
fi
if [ ! -f /app/models/intrusion_model.joblib ]; then
  echo "No trained model found: training the synthetic demo model (flagged as synthetic in the UI)."
  python scripts/generate_synthetic_data.py
  python scripts/train.py --data ../data/synthetic --synthetic --dataset-name synthetic-smoke-test
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"

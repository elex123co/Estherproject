# Viona

ML-based real-time detection of network security threats, with a controlled simulation environment, a rule-based risk engine and a monitoring dashboard.

A decision-support prototype: a FastAPI + scikit-learn backend that classifies network flows with a trained model,
a separate rule-based risk engine, SQLite persistence, and a React/TypeScript dashboard.

It does not replace security analysts, cannot guarantee detection, and flagged records are *potential* intrusions, not confirmed incidents.

## Running it from a URL (hosted)

The dashboard needs the backend process running somewhere that stays on. A browser tab alone cannot run the model. The repo includes a `Dockerfile` that builds the dashboard and serves it and the API from one URL.

1. Deploy the repo to a host that runs Docker containers continuously (Render, Railway, Fly.io, a VPS). Serverless hosts such as Vercel or Netlify functions will not work: the real-time engine is a long-running process.
2. Attach one **persistent disk** (for example mounted at `/var/data`) and set `VIONA_STORAGE=/var/data`. The data and models folders are kept inside it. Without it, the SQLite file and the trained model vanish on every restart.
3. Set `VIONA_ACCESS_PASSWORD`. This puts a password prompt in front of everything. Without it, anyone with the URL can upload data and start sessions.
4. On first start with no model, the container trains the **synthetic demo model** (flagged as synthetic in the UI). For real use, put CICIDS2017 CSVs on the disk and run `python scripts/train.py ...` inside the container.

No external database is needed. Data entered by hand (single-record check, CSV upload) is stored in the same SQLite file.

## Storing results in Supabase (Postgres)

By default Viona keeps results in a local SQLite file. To keep them across restarts on a host without a disk, set one environment variable and the same app stores everything in Postgres:

- `DATABASE_URL`: the connection string from Supabase (Project Settings, Database, Connection string, **Session pooler** or the direct connection; the Transaction pooler also works).

The tables are created automatically on first start, with row level security switched on and no policies, so Supabase's public REST API cannot read them. Only the backend's own connection can. With Postgres the real-time record cap defaults to 50,000 (`NID_MAX_REALTIME_RECORDS`) to respect the free 500 MB limit. The CSV files you upload are still saved on the server's local disk, so after a restart on a free host the results remain but a file cannot be replayed again.

To test against a local Postgres: `TEST_DATABASE_URL=postgresql://... python -m pytest`.

## Real-time detection and the controlled simulation environment

The **Live detection** page scores network flows as they arrive. A background engine takes flows in 100 ms micro-batches, runs the trained model and the risk rules, stores every flow, and streams updates to the browser over Server-Sent Events (`GET /api/realtime/stream`). One session runs at a time, and each session is saved as an ordinary analysis, so alerts, review, exports and reports work on live data.

| Mode | What it does |
|---|---|
| Controlled simulation | A scenario (normal baseline plus timed attack phases) is composed in memory from labelled flows the model was **not trained on** (the held-out test and validation splits, saved as `models/simulation_pool.joblib`). Same seed, same traffic. Attacker addresses use RFC 5737 documentation ranges, normal clients use RFC 1918. |
| Replay | An uploaded CSV is replayed at a chosen flows-per-second rate. |
| External feed | Your own collector posts flows to `POST /api/realtime/ingest` (up to 500 per request, using the model's feature names). |

The page reports flows per second, latency (flow arrival to prediction complete, so it includes up to one 100 ms batch wait), per-phase time to first detection and detection rate, and, when the source knows the labels, live recall, precision and false-positive rate. The model never sees the labels.

Limits and honesty notes:
- The simulator **never sends or generates packets**. It only creates records inside the backend process.
- Rate, duration and total-record caps are enforced (`NID_MAX_REALTIME_RATE`, `NID_MAX_SESSION_SECONDS`, `NID_MAX_REALTIME_RECORDS`).
- Simulated accuracy demonstrates the pipeline. The pool is limited and sampled repeatedly, so it is not a field accuracy estimate.
- Packet capture and extraction of the 78 CICFlowMeter features is **not included**. Run a flow extractor of your own and feed its output to the ingest endpoint.
- Retrain after upgrading (`python scripts/train.py ...`) so the simulation pool exists.

## Quick start

Requirements: Python 3.11+, Node 20+.

```bash
# 1. backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. get a model (choose one)
#    a) real: download CICIDS2017 "MachineLearningCVE" CSVs from
#       https://www.unb.ca/cic/datasets/ids-2017.html into data/CICIDS2017/
python scripts/train.py --data ../data/CICIDS2017 --dataset-name CICIDS2017 --dataset-version MachineLearningCVE
#       (use --max-rows 500000 for a stratified sample if memory or time is limited)
#    b) demo only: synthetic data, flagged as such everywhere in the UI
python scripts/generate_synthetic_data.py && python scripts/train.py --data ../data/synthetic --synthetic --dataset-name synthetic-smoke-test

# 3. run the API (docs at http://localhost:8000/docs)
uvicorn app.main:app --port 8000

# 4. frontend, in another terminal
cd frontend && npm install && npm run dev      # http://localhost:5173
```

Then open **Upload and analyze**, upload a CSV (for the demo model, the generated synthetic file works), start the analysis and review results.

## What is real and what is not

- All dashboard numbers come from stored model output. Nothing is simulated. With no analyses stored, pages show empty states.
- The feature list is **discovered from the training data** and saved with the model, never hardcoded. Uploads are validated against it.
- The synthetic generator exists only to smoke-test the pipeline. A model trained on it carries `is_synthetic` in its metadata and the UI shows a banner. Its metrics mean nothing about real traffic.
- I could not download CICIDS2017 in the build environment, so the pipeline has been verified on synthetic CICIDS-shaped data only. Run the real training on your machine and check the reported per-class results (rare classes such as Heartbleed, Infiltration, SQL injection have very few samples).

## Architecture

```
backend/app/
  ml/         schema, preprocessing, training, evaluation, model store
  risk/       rules.json (configurable) + engine
  services/   validation, prediction, background analysis
  database/   SQLite schema + repository
  api/        routes (system, scans, records)
frontend/src/ pages, components, services (API client), hooks, context, types
```

Three separate outputs are kept apart everywhere: **prediction** (model), **model confidence** (model's own estimate, not calibrated),
**risk level** (rules). Supplied ground-truth labels are stored separately and never treated as predictions.

### ML pipeline (`backend/scripts/train.py`)
Load, strip column names, normalize labels, set non-numeric/infinite values to missing, drop exact duplicates *before* splitting,
stratified 60/20/20 split, feature selection (constant/duplicate columns) on the training split only, fit Random Forest, Decision Tree and
Logistic Regression with the same split, **select on validation macro-F1**, evaluate the winner once on the held-out test split.
The fitted preprocessing + model are saved together (`models/intrusion_model.joblib`) with metadata and evaluation JSON.
Caveat recorded in the metadata: a random split can overestimate performance on unseen capture days.

### Risk engine (`backend/app/risk/rules.json`)
Levels: None (normal), Low, Medium, High, Critical, plus **Needs review** when there is no basis for a severity. Severity comes from the predicted
category; escalation needs confidence **and** record evidence; low confidence only caps severity and flags review. Every record keeps its rule id and reason.
Edit the JSON and restart the API.

### API (see `/docs`)
`GET /api/health`, `/api/model`, `/api/model/evaluation`, `/api/datasets/schema`, `/api/risk/rules`; `POST /api/datasets/upload`, `POST /api/scans/{id}/analyze` (background job, poll `GET /api/scans/{id}`),
`POST /api/predict` (single record); `GET /api/records`, `/api/alerts`, `/api/alerts/{id}`, `PATCH /api/alerts/{id}`; `GET /api/stats/overview|traffic|filter-options`;
`GET /api/scans/{id}/report`, `/api/scans/{id}/export.csv`.

Configuration is by environment variables: `NID_ALLOWED_ORIGINS`, `NID_MAX_UPLOAD_MB` (200), `NID_CHUNK_ROWS`, `NID_MAX_JOBS`, `NID_MAX_QUEUED_JOBS`,
`NID_MAX_FEATURE_ROWS`, `NID_MODEL_DIR`, `NID_DATA_DIR`, `NID_DATABASE_PATH`, `NID_RISK_RULES_PATH`.

## Tests
```bash
cd backend && pytest        # unit tests for the risk engine + end-to-end API tests on a freshly trained model
cd frontend && npm run build
```

## Known limitations
- **No authentication.** Designed for a single user on a trusted machine. Add authentication and authorization before any multi-user or networked deployment.
- Risk rules are record-level. There is no correlation of records into incidents, so counts are flows, not attacks.
- Only CSV flow files with the training feature schema are supported. No pcap/log parsing (extract flows first, e.g. with CICFlowMeter).
- Per-record feature vectors are stored only for flagged records, capped per scan (`NID_MAX_FEATURE_ROWS`). The feature panel shows model-wide importance (tree models only), not per-record explanations.
- Reports: CSV export, and the Reports page prints to PDF via the browser.
- Full CICIDS2017 (~2.8M rows) needs several GB of RAM to train; use `--max-rows` otherwise.

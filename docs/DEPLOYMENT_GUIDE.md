# ManufacturaIQ Deployment Guide

This project deploys as two services:

- Frontend: React + Vite + TypeScript on Vercel.
- Backend: FastAPI on Render.

Do not commit real `.env` files. Configure secrets in the Vercel and Render dashboards.

## Render Backend

Create a Render Web Service from `https://github.com/eswarb-dev/CMTI.git`.

Use these settings:

| Setting | Value |
| --- | --- |
| Root directory | `backend` |
| Runtime | Python 3.12 |
| Build command | `pip install -e .` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |

Add a persistent disk if you want local SQLite auth, dynamic PDF uploads, and dynamic Qdrant vectors to survive redeploys. Mount it at:

```text
/var/data
```

Recommended Render environment variables:

```env
APP_ENV=production
LOG_LEVEL=INFO
CORS_ALLOWED_ORIGINS=["https://your-vercel-app.vercel.app"]

AUTH_JWT_SECRET=<generate-a-long-random-secret>
AUTH_ACCESS_TOKEN_MINUTES=480

DATABASE_URL=sqlite:////var/data/manufacturaiq.db
QDRANT_PATH=/var/data/vector_store

DOCUMENT_UPLOAD_ENABLED=true
DOCUMENT_STORAGE_PATH=/var/data/documents
DOCUMENT_MAX_UPLOAD_MB=50
DOCUMENT_DYNAMIC_COLLECTION=manufacturaiq_dynamic_documents
DOCUMENT_INGEST_BATCH_SIZE=32

EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
EMBEDDING_WARMUP_ENABLED=false
QUERY_EMBEDDING_CACHE_SIZE=128
QUERY_TOTAL_TIMEOUT_SECONDS=20

GEMINI_API_KEY=<your-gemini-api-key>
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash-lite
GEMINI_MODEL_FALLBACK_ENABLED=true
GEMINI_THINKING_LEVEL=low
GEMINI_TOTAL_BUDGET_SECONDS=15
GEMINI_PRIMARY_TIMEOUT_SECONDS=6
GEMINI_REQUEST_TIMEOUT_SECONDS=10
GEMINI_RETRY_BACKOFF_SECONDS=0.5
GEMINI_MAX_ATTEMPTS=2
GEMINI_MAX_OUTPUT_TOKENS=3072

TYPESAFE_API_KEY=<optional-typesafe-key>
TYPESAFE_MODEL=<optional-typesafe-model>
JEV_ENABLED=true
JEV_REVIEW_ENABLED=true
JEV_ROUTE_THRESHOLD=0.50
JEV_TIMEOUT_SECONDS=10
JEV_MAX_RETRIES=1
```

If `TYPESAFE_API_KEY` is not set, the app uses deterministic routing fallback and final review fails closed to `HUMAN_REVIEW`.

Generate a JWT secret locally with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

After the backend is live, verify:

```text
https://your-render-service.onrender.com/health
https://your-render-service.onrender.com/ready
```

Create a local account from the Render shell if needed:

```bash
python scripts/create_local_user.py
```

## Vercel Frontend

Create a Vercel project from the same GitHub repository.

Use these settings:

| Setting | Value |
| --- | --- |
| Framework preset | Vite |
| Root directory | `frontend` |
| Build command | `npm run build` |
| Output directory | `dist` |

Set this Vercel environment variable:

```env
VITE_API_BASE_URL=https://your-render-service.onrender.com
```

Do not put backend secrets in Vercel. `VITE_*` variables are compiled into the browser bundle.

After the Vercel app is deployed, copy its production URL back into Render:

```env
CORS_ALLOWED_ORIGINS=["https://your-vercel-app.vercel.app"]
```

Redeploy the Render backend after changing CORS.

## Data Notes

The deploy branch intentionally excludes local databases, uploaded PDFs, generated vector stores, and bulky dataset artifacts. A fresh Render deployment starts without the local static corpus unless you rebuild or restore the vector store/data outside Git.

Dynamic uploaded PDFs are stored separately from manufacturing SQLite tables. Uploaded PDFs should use `DOCUMENT_STORAGE_PATH` and the dynamic Qdrant collection. They are not written into production, maintenance, quality, alarm, or telemetry tables.

For production-like document answers, choose one of these approaches:

- Upload PDFs through the app after deployment.
- Rebuild the static RAG index in a Render shell and keep it on the persistent disk.
- Restore a prepared vector-store artifact to the persistent disk.

## Deployment Order

1. Deploy Render backend with the environment variables above.
2. Confirm `/health` returns `ok`.
3. Deploy Vercel frontend with `VITE_API_BASE_URL` pointing at Render.
4. Add the final Vercel URL to Render `CORS_ALLOWED_ORIGINS`.
5. Redeploy Render.
6. Open the Vercel URL and submit a query.
7. Confirm evidence, citations, and any `HUMAN_REVIEW` banner render as expected.

# ManufacturaIQ Backend

## Requirements

- Windows PowerShell
- Python 3.12.x
- Project virtual environment at `D:\CMTI\.venv`
- Node.js and npm for the frontend

## Python Environment

From PowerShell:

```powershell
cd D:\CMTI\backend
D:\CMTI\.venv\Scripts\python.exe --version
```

Use `D:\CMTI\.venv\Scripts\python.exe` for backend commands.

## Environment Configuration

Backend environment values live in:

```text
D:\CMTI\backend\.env
```

Example structure only, without real secrets:

```text
GEMINI_API_KEY=<your-key>
GEMINI_MODEL=gemini-3.8-flash

TYPESAFE_API_KEY=

DOCUMENT_UPLOAD_ENABLED=true
DOCUMENT_STORAGE_PATH=D:\CMTI\data\documents
DOCUMENT_MAX_UPLOAD_MB=50
DOCUMENT_DYNAMIC_COLLECTION=manufacturaiq_dynamic_documents
DOCUMENT_INGEST_BATCH_SIZE=32

AUTH_JWT_SECRET=
AUTH_ACCESS_TOKEN_MINUTES=480
```

Do not commit or paste real API keys into documentation.

## Local Prototype Login

ManufacturaIQ uses a separate local SQLite authentication database for the prototype:

```text
D:\CMTI\backend\data\auth.db
```

The manufacturing database remains separate at `D:\CMTI\backend\data\manufacturaiq.db`.

1. Generate a local JWT secret:

```powershell
D:\CMTI\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
```

2. Add the generated value to `D:\CMTI\backend\.env`:

```text
AUTH_JWT_SECRET=<generated-value>
AUTH_ACCESS_TOKEN_MINUTES=480
```

Do not commit the generated secret.

3. Create a local prototype user:

```powershell
cd D:\CMTI\backend
D:\CMTI\.venv\Scripts\python.exe scripts\create_local_user.py
```

The script prompts for username, display name, role, password, and password confirmation. Password input is not echoed and no default demo credentials are created.

4. Start backend and frontend, then sign in with the local username and password:

```powershell
cd D:\CMTI
D:\CMTI\start.ps1
```

Logout removes only the local browser auth token. Conversations, uploaded documents, manufacturing data, and knowledge-base state are not deleted. This local prototype stores the bearer token in `localStorage` under `manufacturaiq.auth.token.v1`; production deployment should use a more secure cookie or server-side session strategy.

## Guest Mode

ManufacturaIQ can be used without signing in. Guest users can open the app, ask engineering questions, view the Knowledge Base, and upload PDFs according to the current prototype document behavior.

Guest conversation history remains browser-local in the same browser storage used by the frontend. It is not stored in `auth.db`.

## Create Local Account

Users may create a local account from the application UI. Accounts are stored locally in:

```text
D:\CMTI\backend\data\auth.db
```

Registration creates a local profile and signs the user in immediately with the same local JWT session used by manual login.

## Current Prototype Limitation

Local accounts currently provide identity/profile and session restore only. They do not provide cloud synchronization, per-user document isolation, server-side conversation persistence, or private document ownership. Guest and authenticated users use the same prototype knowledge base and browser-local conversation model in this pass.

## Start Backend

```powershell
cd D:\CMTI\backend
D:\CMTI\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Verify Health

Open:

```text
http://127.0.0.1:8000/health
```

Expected: `status` is `ok`.

Ready check:

```text
http://127.0.0.1:8000/ready
```

Expected: `status` is `ready`.

## Start Frontend

```powershell
cd D:\CMTI\frontend
npm install
npm run dev
```

Then open:

```text
http://localhost:5173
```

Use one frontend API base URL:

```text
VITE_API_BASE_URL=http://localhost:8000
```

## Gemini Configuration

If `GEMINI_API_KEY` is configured, live grounded natural-language reasoning is enabled.

If no Gemini key is configured, retrieval and agents can still run, reasoning reports unavailable, and final results generally fail closed to `HUMAN_REVIEW`.

## TypeSafe / Jev Note

TypeSafe/Jev is optional for the demo. If `TYPESAFE_API_KEY` is absent, routing uses deterministic fallback and final Jev review fails closed to `HUMAN_REVIEW`. The application still works.

## PDF Upload / Knowledge Base

Use the UI:

```text
Sources & Evidence -> Add PDF
```

or:

```text
Knowledge Base -> Add PDF
```

Uploaded PDFs are stored, indexed, and retrievable immediately from normal chat through the dynamic document knowledge base.

## Common Errors

If the UI shows `Offline` or `Backend is unreachable`:

1. Ensure the backend is running on port `8000`.
2. Verify the frontend has `VITE_API_BASE_URL=http://localhost:8000`.
3. Open `http://127.0.0.1:8000/health` and confirm `status` is `ok`.

## Demo Startup Checklist

1. Start backend.
2. Verify `/health`.
3. Start frontend.
4. Confirm the UI status is `Online`.
5. Upload demo PDF.
6. Ask a query.
7. Verify the source card.
8. Delete the demo PDF if temporary.

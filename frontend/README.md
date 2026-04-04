# Frontend

Minimal React + Vite sandbox for learning the admin UI without replacing the
working FastAPI templates yet.

## Run

1. Start the FastAPI backend:

```bash
./.venv/bin/python -m uvicorn server:app --reload --host 127.0.0.1 --port 8002
```

2. Install frontend dependencies:

```bash
cd frontend
npm install
```

3. Start the React dev server:

```bash
npm run dev
```

The Vite dev server runs on `http://127.0.0.1:5173` and proxies `/admin` and
`/oauth` calls to the FastAPI backend on `http://127.0.0.1:8002`.

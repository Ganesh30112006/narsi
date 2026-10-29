# GovPII Guard

Detection of government-issued PII embedded in documents and data. Anyone can upload a file and get its
results without an account; only administrators sign in.

| Folder | What | Details |
| --- | --- | --- |
| [Frontend/](Frontend/) | React 19 · TypeScript · Vite | [Frontend/README.md](Frontend/README.md) |
| [Backend/](Backend/) | FastAPI · SQLAlchemy · PyMuPDF · Tesseract · spaCy | [Backend/README.md](Backend/README.md) |

Everything runs natively, with no Docker. First-time setup is in each folder's README. After that, run each in its own terminal:

```bash
# 1. API on http://127.0.0.1:8000
cd Backend
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. Web app on http://localhost:5173 (proxies /api to the backend)
cd Frontend
npm run dev:api
```

Open http://localhost:5173 for the public scanner and http://localhost:5173/admin/login for administrators.
To try the UI without the backend, run `npm run dev` in `Frontend/` instead (mock mode, in-browser sample data).

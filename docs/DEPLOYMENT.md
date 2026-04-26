# Deployment guide

This project is designed to run with Docker Compose out of the box. For public
hosting, you can split it across managed providers or run the whole stack on
one VM.

## Option A — Single VM (Fly.io, DigitalOcean, Hetzner, any Docker host)

The simplest path. Copy the repo to the VM and run Docker Compose.

```bash
ssh my-vm
git clone <repo> soc2-reviewer && cd soc2-reviewer
cp .env.example .env
cp backend/.env.example backend/.env
# edit backend/.env — set OPENAI_API_KEY or another provider
docker compose up -d --build
```

Put a reverse proxy (Caddy, Nginx, Traefik) in front of the frontend on port
3000. Example Caddy config:

```
soc2.example.com {
    reverse_proxy localhost:3000
}
```

The frontend internally proxies `/api/backend/*` to the backend, so only port
3000 needs to be exposed publicly.

## Option B — Split: Frontend on Vercel, Backend on Railway/Render

### Backend on Railway

1. New Project → Deploy from GitHub repo, select the `backend/` directory.
2. Add a PostgreSQL plugin. Then in the Postgres settings:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
3. Set environment variables (from `backend/.env.example`):
   - `DATABASE_URL` (Railway provides this — format as
     `postgresql+psycopg2://USER:PASS@HOST:PORT/DB`)
   - `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY` (or your chosen provider)
   - `CORS_ORIGINS` → your Vercel URL, e.g. `https://soc2.vercel.app`
4. Expose the Railway URL. Verify `/health`.

### Backend on Render

Similar to Railway — use a Web Service + a Render Postgres (with `pgvector`
extension enabled in a pre-deploy SQL command).

### Backend on Fly.io

```bash
cd backend
fly launch --no-deploy         # picks up the Dockerfile
fly postgres create --name soc2-db
fly postgres attach --app soc2-backend soc2-db
fly secrets set OPENAI_API_KEY=... LLM_PROVIDER=openai CORS_ORIGINS=https://soc2.vercel.app
fly deploy
fly postgres connect -a soc2-db -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Frontend on Vercel

1. Import the GitHub repo, set the **root directory** to `frontend/`.
2. Build command: `npm run build` (default). Install command: `npm install --legacy-peer-deps`.
3. Environment variables:
   - `BACKEND_URL` → public backend URL (e.g., `https://soc2-backend.fly.dev`)
   - `NEXT_PUBLIC_API_BASE` → `/api/backend`
4. Deploy. Vercel will rewrite `/api/backend/*` → `BACKEND_URL` via `next.config.js`.

## Environment variable reference

See `backend/.env.example` and `frontend/.env.example` for the complete list.
The ones you almost always need to set:

| Variable                 | Where        | Purpose                                |
| ------------------------ | ------------ | -------------------------------------- |
| `OPENAI_API_KEY`         | backend      | Enable chat + summary + embeddings     |
| `LLM_PROVIDER`           | backend      | openai / anthropic / groq / ollama     |
| `DATABASE_URL`           | backend      | Postgres with pgvector enabled         |
| `CORS_ORIGINS`           | backend      | Comma-separated allowed frontend URLs  |
| `BACKEND_URL`            | frontend     | Where the Next.js server proxies to    |

## Post-deployment checklist

- [ ] `/health` returns `{"status":"ok"}`.
- [ ] Upload a known-good SOC 2 report. Validation findings appear within 20s.
- [ ] Suggested questions populate.
- [ ] Chat returns a citation-grounded answer with a `Confidence:` label.
- [ ] Summary tab renders a rating + readiness badge.
- [ ] Delete the report → 404 on subsequent GET.
- [ ] CORS rejects an untrusted origin.
- [ ] Rate limiting triggers after the configured burst.

## Scaling notes

- Backend is stateless; scale horizontally. All shared state lives in Postgres.
- For very large reports, increase `MAX_UPLOAD_MB` and consider async ingestion
  (the current pipeline is synchronous; a 200-page PDF parses in ~10–15s).
- Tune `CHUNK_SIZE`, `CHUNK_OVERLAP`, and `TOP_K` to match the LLM's context
  window and your cost profile.
- The HNSW index (`m=16, ef_construction=64`) is sized for ~100k chunks. For
  higher volumes, rebuild with larger parameters or switch to IVFFLAT.

## Observability

Python logs go to stdout in the FastAPI-standard format. Point Loki / Datadog /
CloudWatch at the container. Add a `/metrics` endpoint if you need Prometheus.

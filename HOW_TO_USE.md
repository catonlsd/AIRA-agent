# How to use AIRA-X

A step-by-step guide to clone, configure, run, and use AIRA-X — no prior context
needed.

## 1. Clone

```bash
git clone https://github.com/catonlsd/AIRA-agent.git
cd AIRA-agent
```

## 2. Configure the backend

```bash
cd backend
cp .env.example .env
```
Edit `.env` and set at least one LLM key. Default provider is Groq:
```
LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
```
(Get a free key at https://console.groq.com.) To use OpenAI/Gemini instead, set
`LLM_PROVIDER=openai|gemini` and the matching `*_API_KEY`.

## 3. Start the backend

```bash
python -m venv venv
# Windows: venv\Scripts\activate   |   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
First run downloads the local embedding model (~80 MB) the first time you ask a
document question. Verify it's up:
```bash
curl http://localhost:8000/health     # {"status": ...}
curl http://localhost:8000/ready      # {"ready": true, "checks": {...}}
```

## 4. Start the frontend

In a second terminal:
```bash
cd frontend
npm install
npm run dev
```
Open **http://localhost:3000**. (If your backend isn't on `localhost:8000`, create
`frontend/.env.local` with `NEXT_PUBLIC_API_URL=http://your-backend:8000`.)

## 5. Chat

Type in the bottom composer and press Enter. Answers stream in token-by-token.

Try:
- `Hello` / `Who are you?` — conversational
- `Explain vector databases` — a knowledge answer (streamed)
- `What's the latest news on AI?` — web research with sources
- `Run git status` — execution (safe actions run; risky ones ask for approval)

AIRA-X remembers recent turns in the conversation, so follow-ups like
"make that shorter" or "what did you just say?" work.

## 6. Upload and ask about documents

1. Click the **📎 paperclip** in the composer.
2. Choose a PDF / DOCX / TXT / MD file. A chip appears: `myfile.pdf`.
3. Ask about it:
   - `Summarize this document`
   - `What does the report say about revenue?`
4. Answers are grounded in your file with **citations** (file + page). If the
   answer isn't in your documents, AIRA-X says so honestly instead of guessing.

Documents stay available for the whole conversation even if you dismiss the chip.

## 7. Approvals (execution)

Risky actions (e.g. `git commit`, `git push`, package installs) pause and show an
**approval card** — approve or reject before anything runs.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Backend won't start: `GROQ_API_KEY is required` | Set the key in `backend/.env`. |
| `/ready` returns 503 | Check the `checks` field (database/LLM). |
| UI can't reach backend | Set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` and restart `npm run dev`. |
| Answers don't stream | Hard-refresh; ensure the backend is the current build and reachable. |
| Document answer says "couldn't find" | The content may not be in the file, or re-upload; try a more specific question. |

## Run with Docker (alternative)

```bash
cp backend/.env.example backend/.env   # set GROQ_API_KEY
docker compose up --build
# frontend http://localhost:3000 · backend http://localhost:8000
```

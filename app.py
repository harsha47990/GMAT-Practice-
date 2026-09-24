"""GMAT mock-exam web app (FastAPI backend).

Run:  python -m uvicorn app:app --reload --port 8100
Then open http://127.0.0.1:8100
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import SECTIONS, TYPE_LABELS
from engine.bank import load_bank, filter_questions
from engine.session import Session
from analysis.report_card import generate_report, quick_report

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="GMAT Mock Exam")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# In-memory session store (single local user).
SESSIONS: dict[str, Session] = {}


# ── Request models ──────────────────────────────────────────────────────

class StartReq(BaseModel):
    mode: str                  # "full" | "practice"
    qtype: str | None = None
    count: int = 10
    timed: bool = True


class AnswerReq(BaseModel):
    sid: str
    qid: str
    choice: int


class EditReq(BaseModel):
    sid: str
    qid: str
    choice: int


class SidReq(BaseModel):
    sid: str


def _get(sid: str) -> Session:
    sess = SESSIONS.get(sid)
    if sess is None:
        raise HTTPException(404, "Session not found")
    return sess


# ── Pages ───────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ── API ─────────────────────────────────────────────────────────────────

@app.get("/api/topics")
def topics():
    """Available practice topics with how many questions exist for each."""
    bank = load_bank()
    out = []
    for name, cfg in SECTIONS.items():
        for t in cfg["types"]:
            n = len(filter_questions(bank, qtype=t))
            out.append({"type": t, "label": TYPE_LABELS[t], "section": name, "available": n})
    return {"topics": out, "bank_size": len(bank)}


@app.post("/api/start")
def start(req: StartReq):
    if req.mode == "full":
        sess = Session.full_exam()
        if not sess.bank:
            raise HTTPException(400, "Question bank is empty. Build it first.")
    elif req.mode == "practice":
        if not req.qtype:
            raise HTTPException(400, "Practice mode requires a qtype.")
        sess = Session.practice(req.qtype, req.count, req.timed)
        if not sess.sections[0].engine.pool:
            raise HTTPException(400, f"No questions available for {req.qtype}.")
    else:
        raise HTTPException(400, "mode must be 'full' or 'practice'")

    SESSIONS[sess.sid] = sess
    return sess.state_payload()


@app.get("/api/state")
def state(sid: str):
    return _get(sid).state_payload()


@app.post("/api/answer")
def answer(req: AnswerReq):
    sess = _get(req.sid)
    sess.submit_answer(req.qid, req.choice)
    return sess.state_payload()


@app.post("/api/edit")
def edit(req: EditReq):
    sess = _get(req.sid)
    ok = sess.edit_answer(req.qid, req.choice)
    payload = sess.state_payload()
    payload["edit_accepted"] = ok
    return payload


@app.post("/api/confirm-section")
def confirm_section(req: SidReq):
    sess = _get(req.sid)
    sess.confirm_section()
    return sess.state_payload()


@app.get("/api/analytics")
def analytics(sid: str):
    """Concise, no-AI analytics summary (works fully offline)."""
    sess = _get(sid)
    if not sess.finished or not sess.results:
        raise HTTPException(400, "Attempt is not finished yet.")
    return {"markdown": quick_report(sess.results)}


@app.post("/api/report")
def report(req: SidReq):
    sess = _get(req.sid)
    if not sess.finished or not sess.results:
        raise HTTPException(400, "Attempt is not finished yet.")
    markdown = generate_report(sess.results)
    return {"markdown": markdown}


# cd GMAT
# python -m authoring.build_bank            # already done, re-run anytime
# python -m authoring.generate_questions --target 100
# python -m uvicorn app:app --port 8100     # open http://127.0.0.1:8100
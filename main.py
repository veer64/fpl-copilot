from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from agent import run_agent

app = FastAPI()

# Single shared conversation history (fine for now - single user, in-memory only)
conversation_history = []

@app.get("/health")
def health_check():
    # The master plan's contract: {status, git_sha, model_versions,
    # data_freshness_by_source, db_ok} -- plus last_run and reasons, so a
    # failed or missing pipeline run surfaces HERE instead of only in an
    # unread status file. The old one-liner returned ok while Postgres was
    # unreachable (observed live 2026-08-31); this one touches the DB.
    from model_tools import health
    return health()

class ChatRequest(BaseModel):
    message: str

@app.post("/chat")
def chat(request: ChatRequest):
    global conversation_history
    answer, conversation_history = run_agent(request.message, conversation_history)
    return {"answer": answer}

@app.post("/reset")
def reset_conversation():
    global conversation_history
    conversation_history = []
    return {"status": "conversation reset"}

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")
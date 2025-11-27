from fastapi import FastAPI

app = FastAPI(title="Agent Orchestrator")

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "agent-orchestrator"}

@app.post("/ask")
def ask_agent(query: str):
    return {"answer": "Service operational", "sources": []}
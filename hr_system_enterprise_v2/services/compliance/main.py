from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Compliance Service")

class Shift(BaseModel):
    start_time: str
    end_time: str

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "compliance"}

@app.post("/validate")
def validate_schedule(shifts: List[Shift]):
    # Placeholder logika da zadovolji interface
    return {"is_compliant": True, "violations": []}
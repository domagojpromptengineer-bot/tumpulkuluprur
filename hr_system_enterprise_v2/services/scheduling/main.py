from fastapi import FastAPI

app = FastAPI(title="Scheduling Service")

@app.get("/")
def health_check():
    return {"status": "healthy", "service": "scheduling"}

@app.post("/generate")
def generate_schedule():
    return {"status": "optimal", "schedule": []}
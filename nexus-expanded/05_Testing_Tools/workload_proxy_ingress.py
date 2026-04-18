from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import uvicorn
import logging

logger = logging.getLogger(__name__)

app = FastAPI(title="NEXUS Workload Ingress", version="3.0")
orchestrator = None

class WorkloadIntent(BaseModel):
    """Workload intent from OS/scheduler."""
    cpu_zones: list[float] = [0.0, 0.0, 0.0, 0.0]
    gpu_zones: list[float] = [0.0, 0.0, 0.0, 0.0]
    mem_load: float = 0.0

@app.post("/predict")
async def ingest_intent(intent: WorkloadIntent, tasks: BackgroundTasks):
    """
    Receive workload intent and trigger asynchronous thermal prediction.
    
    Returns immediately to keep the ingress port responsive.
    The actual control loop runs in the background.
    """
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    # Hand off to background task to avoid blocking the API
    tasks.add_task(orchestrator.process_intent, intent.dict())
    
    return {
        "status": "intent_received",
        "message": "Thermal prediction and actuation processing...",
        "deterministic_gap": "closing"
    }

@app.get("/status")
async def get_status():
    """Get current orchestrator statistics."""
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    
    return {
        "status": "operational",
        "stats": orchestrator.get_stats()
    }

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}

def start_ingress(orch_instance, host="0.0.0.0", port=8000):
    """
    Start the FastAPI ingress server.
    
    Args:
        orch_instance: NexusOrchestrator instance
        host: Bind address
        port: Bind port
    """
    global orchestrator
    orchestrator = orch_instance
    logger.info(f"Starting NEXUS Ingress on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

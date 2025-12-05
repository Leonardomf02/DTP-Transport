"""DTP API - FastAPI server with WebSocket for real-time dashboard."""

import asyncio
import json
import time
import threading
import os
from typing import Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.simulation import SimulationEngine, SimulationConfig, SimulationState
from src.client import ClientMode


engine: Optional[SimulationEngine] = None
connected_clients: Set[WebSocket] = set()
clients_lock = threading.Lock()
main_loop: Optional[asyncio.AbstractEventLoop] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, main_loop
    
    main_loop = asyncio.get_running_loop()
    engine = SimulationEngine()
    
    def on_metrics_update(metrics):
        try:
            if main_loop and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(broadcast_metrics(metrics), main_loop)
        except Exception:
            pass
    
    engine.set_on_metrics_update(on_metrics_update)
    
    yield
    
    if engine:
        engine.stop()
    main_loop = None


app = FastAPI(
    title="DTP - Deadline-aware Transport Protocol",
    description="Simulation and demonstration API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SimulationStartRequest(BaseModel):
    mode: str = "dtp"
    critical_count: int = 50
    high_count: int = 200
    medium_count: int = 500
    low_count: int = 1000
    simulate_congestion: bool = True
    congestion_level: float = 0.3


class SimulationResponse(BaseModel):
    status: str
    message: str


@app.post("/simulation/start", response_model=SimulationResponse)
async def start_simulation(request: SimulationStartRequest):
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    if engine.is_running:
        engine.stop()
        time.sleep(0.5)
    
    try:
        mode = ClientMode(request.mode)
    except ValueError:
        mode = ClientMode.DTP
    
    config = SimulationConfig(
        mode=mode,
        critical_count=request.critical_count,
        high_count=request.high_count,
        medium_count=request.medium_count,
        low_count=request.low_count,
        simulate_congestion=request.simulate_congestion,
        congestion_level=request.congestion_level
    )
    
    threading.Thread(target=engine.start, args=(config,), daemon=True).start()
    
    return SimulationResponse(
        status="started",
        message=f"Simulation started in {mode.value} mode"
    )


@app.post("/simulation/stop", response_model=SimulationResponse)
async def stop_simulation():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    engine.stop()
    
    return SimulationResponse(
        status="stopped",
        message="Simulation stopped"
    )


@app.post("/simulation/pause", response_model=SimulationResponse)
async def pause_simulation():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    engine.pause()
    
    return SimulationResponse(
        status="paused",
        message="Simulation paused"
    )


@app.post("/simulation/resume", response_model=SimulationResponse)
async def resume_simulation():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    engine.resume()
    
    return SimulationResponse(
        status="running",
        message="Simulation resumed"
    )


@app.get("/simulation/status")
async def get_status():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    return engine.get_current_metrics()


@app.get("/simulation/results")
async def get_results():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    return engine.get_results()


@app.get("/comparison")
async def get_comparison():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    return engine.get_comparison()


@app.post("/comparison/clear", response_model=SimulationResponse)
async def clear_comparison():
    global engine
    
    if not engine:
        raise HTTPException(status_code=500, detail="Engine not initialized")
    
    engine.clear_results()
    
    return SimulationResponse(
        status="cleared",
        message="Comparison results cleared"
    )


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    with clients_lock:
        connected_clients.add(websocket)
    
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text(json.dumps({"type": "keepalive"}))
                except:
                    break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        with clients_lock:
            connected_clients.discard(websocket)


async def broadcast_metrics(metrics: dict):
    with clients_lock:
        if not connected_clients:
            return
        clients_copy = list(connected_clients)
    
    message = json.dumps({
        "type": "metrics",
        "data": metrics
    })
    
    disconnected = []
    for client in clients_copy:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.append(client)
    
    if disconnected:
        with clients_lock:
            for client in disconnected:
                connected_clients.discard(client)


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "DTP API"}


FRONTEND_BUILD_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")

if os.path.exists(FRONTEND_BUILD_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_BUILD_DIR, "assets")), name="assets")
    
    @app.get("/")
    async def serve_frontend():
        return FileResponse(os.path.join(FRONTEND_BUILD_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""
Clash IP Checker - Web Configuration Interface
FastAPI backend with SSE progress and REST API
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers.api import router as api_router
from routers.views import router as views_router
from runtime_port import load_port_preference, save_port_preference, select_available_port

from contextlib import asynccontextmanager
from state import state

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown
    print("[Web] Shutting down, cleaning up resources...")
    await state.checker.stop()

app = FastAPI(title="Clash Verge IP Checker Auto", lifespan=lifespan)

# Mount supporting static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Ensure exports directory
exports_dir = "exports"
os.makedirs(exports_dir, exist_ok=True)
app.mount("/exports", StaticFiles(directory=exports_dir), name="exports")

# Include Routers
app.include_router(views_router)
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("CLASH_CHECKER_HOST", "127.0.0.1")
    port_state = Path(__file__).resolve().parent / ".runtime" / "port.json"
    selected_port = select_available_port(load_port_preference(port_state))
    port = selected_port.port
    save_port_preference(port_state, port)
    public_base_url = os.environ.get("CLASH_CHECKER_PUBLIC_BASE_URL", "").strip()
    local_url = f"http://127.0.0.1:{port}"

    print(f"[Web] Local URL: {local_url}")
    if public_base_url:
        print(f"[Web] LAN/Public URL: {public_base_url.rstrip('/')}")
    elif host == "0.0.0.0":
        print("[Web] Listening on all interfaces. Set CLASH_CHECKER_PUBLIC_BASE_URL for stable import URLs.")

    uvicorn.run(app, host=host, port=port)

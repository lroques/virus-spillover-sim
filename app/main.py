from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .model import DEFAULTS, model_metadata, simulate
from .render import render_layer_png

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Virus Spillover Simulator", version="1.3.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SimulationRequest(BaseModel):
    D: float = Field(DEFAULTS["D"], ge=0.0, le=10000.0)
    beta0: float = Field(DEFAULTS["beta0"], ge=0.0, le=1e-6)
    beta1: float = Field(DEFAULTS["beta1"], ge=0.0, le=1e-6)
    b0: float = Field(DEFAULTS["b0"], ge=0.0, le=5.0)
    d0: float = Field(DEFAULTS["d0"], ge=0.0, le=5.0)
    max_chain_length: int = Field(DEFAULTS["max_chain_length"], ge=0, le=500)
    optimum: float = Field(DEFAULTS["optimum"], ge=-3.0, le=3.0)
    duration: float = Field(DEFAULTS["duration"], ge=1.0, le=50.0)
    frames: int = Field(DEFAULTS["frames"], ge=61, le=301)
    seed: int = Field(DEFAULTS["seed"], ge=0, le=2_147_483_647)


_FIELD_LABELS = {
    "D": "Spatial variance D",
    "beta0": "beta0",
    "beta1": "beta1",
    "b0": "b0",
    "d0": "d0",
    "max_chain_length": "Max length of transmission chains",
    "optimum": "Target optimum O_s",
    "duration": "Duration",
    "frames": "Frames",
    "seed": "Random seed",
}


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Return readable validation errors instead of a list of error objects."""
    messages: list[str] = []
    for error in exc.errors():
        loc = [part for part in error.get("loc", ()) if part not in {"body", "query", "path"}]
        field = str(loc[-1]) if loc else "parameter"
        label = _FIELD_LABELS.get(field, field)
        message = str(error.get("msg", "invalid value"))
        messages.append(f"{label}: {message}")
    detail = "Invalid parameter values. " + "; ".join(messages) if messages else "Invalid parameter values."
    return JSONResponse(status_code=422, content={"detail": detail})


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/model")
def api_model() -> JSONResponse:
    return JSONResponse(model_metadata())


@app.get("/api/layer/{layer}.png")
def api_layer(
    layer: str,
    D: float = Query(DEFAULTS["D"], ge=0.0, le=10000.0),
    beta0: float = Query(DEFAULTS["beta0"], ge=0.0, le=1e-6),
    beta1: float = Query(DEFAULTS["beta1"], ge=0.0, le=1e-6),
) -> Response:
    try:
        payload, scale = render_layer_png(layer, D=D, beta0=beta0, beta1=beta1)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown layer")
    headers = {
        "Cache-Control": "no-store",
        "X-Scale-Min": f"{scale['min']:.12g}",
        "X-Scale-Max": f"{scale['max']:.12g}",
        "X-Scale-Mode": scale["mode"],
        "X-Layer-Label": scale["label"],
    }
    return Response(content=payload, media_type="image/png", headers=headers)


@app.post("/api/simulate")
def api_simulate(req: SimulationRequest) -> JSONResponse:
    try:
        out = simulate(
            D=req.D,
            beta0=req.beta0,
            beta1=req.beta1,
            b0=req.b0,
            d0=req.d0,
            max_chain_length=req.max_chain_length,
            optimum=req.optimum,
            duration=req.duration,
            frames=req.frames,
            seed=req.seed,
        )
        return JSONResponse(out)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

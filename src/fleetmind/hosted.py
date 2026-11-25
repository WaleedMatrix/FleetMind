"""Stateless inference surface for the isolated portfolio service."""

import asyncio
import os
from collections import deque
from contextlib import asynccontextmanager
from time import monotonic
from typing import Annotated

import joblib
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from fleetmind.api.inference import classify_alert, to_model_frame
from fleetmind.api.schemas import MachineReading
from fleetmind.artifacts import MODEL_PATH, verify_artifacts
from fleetmind.config import MODEL_VERSION, PRIMARY_THRESHOLD

BODY_LIMIT = 2048
REQUESTS_PER_MINUTE = 30


class HostedReading(MachineReading):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)

    air_temperature_k: Annotated[float, Field(ge=250, le=400)]
    process_temperature_k: Annotated[float, Field(ge=250, le=450)]
    rotational_speed_rpm: Annotated[float, Field(gt=0, le=5000)]
    torque_nm: Annotated[float, Field(ge=0, le=200)]
    tool_wear_min: Annotated[float, Field(ge=0, le=1000)]


@asynccontextmanager
async def lifespan(api):
    verify_artifacts()
    api.state.model = joblib.load(MODEL_PATH)
    # Loading and the first prediction are included in readiness time.
    warmup = HostedReading(
        machine_type="L",
        air_temperature_k=300,
        process_temperature_k=310,
        rotational_speed_rpm=1500,
        torque_nm=40,
        tool_wear_min=100,
    )
    predict_score(api.state.model, warmup)
    api.state.slot = asyncio.Lock()
    api.state.requests = deque(maxlen=REQUESTS_PER_MINUTE)
    yield


app = FastAPI(
    title="FleetMind portfolio inference",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    redirect_slashes=False,
)


def predict_score(model, reading):
    return float(model.predict_proba(to_model_frame(reading))[0, 1])


async def bounded_reading(request):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "application/json"
    ):
        raise HTTPException(415, "Use a JSON sensor reading.")
    length = request.headers.get("content-length")
    if length and (
        not length.isdecimal() or len(length) > 4 or int(length) > BODY_LIMIT
    ):
        raise HTTPException(413, "The reading exceeds 2 KiB.")
    body = bytearray()
    try:
        async with asyncio.timeout(2):
            async for chunk in request.stream():
                if len(body) + len(chunk) > BODY_LIMIT:
                    raise HTTPException(413, "The reading exceeds 2 KiB.")
                body.extend(chunk)
        return HostedReading.model_validate_json(body)
    except ValidationError:
        raise HTTPException(
            422, "Use valid numeric sensor readings within the demo limits."
        ) from None
    except (ClientDisconnect, TimeoutError):
        raise HTTPException(408, "The reading upload timed out.") from None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/infer")
async def infer(request: Request):
    state = request.app.state
    now = monotonic()
    while state.requests and state.requests[0] <= now - 60:
        state.requests.popleft()
    if len(state.requests) == REQUESTS_PER_MINUTE:
        retry = max(1, int(state.requests[0] + 61 - now))
        raise HTTPException(
            429,
            "The shared demo rate limit was reached.",
            headers={"Retry-After": str(retry)},
        )
    state.requests.append(now)
    if state.slot.locked():
        raise HTTPException(
            429, "The demo is processing another reading.", headers={"Retry-After": "2"}
        )
    async with state.slot:
        reading = await bounded_reading(request)
        score = await run_in_threadpool(predict_score, state.model, reading)
    return JSONResponse(
        {
            "model_version": MODEL_VERSION,
            "failure_score": score,
            "predicted_failure": score >= PRIMARY_THRESHOLD,
            "alert_level": classify_alert(score),
        },
        headers={"Cache-Control": "no-store"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        workers=1,
        proxy_headers=False,
        access_log=False,
        limit_concurrency=12,
        timeout_keep_alive=3,
        timeout_graceful_shutdown=5,
    )

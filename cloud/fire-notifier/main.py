import base64
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request


logging.basicConfig(level=logging.INFO)
app = FastAPI(title="SentialX Fire Notifier", version="1.0.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sentialx-fire-notifier"}


@app.post("/pubsub/fire")
async def notify_fire(request: Request) -> dict[str, Any]:
    envelope = await request.json()
    message = envelope.get("message")
    if not isinstance(message, dict) or not message.get("data"):
        raise HTTPException(status_code=400, detail="Pub/Sub message.data is required")

    try:
        alert = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub data") from exc

    required = {"event_id", "customer_id", "camera_id", "captured_at", "gcs_uri"}
    missing = sorted(required - alert.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing alert fields: {', '.join(missing)}",
        )

    log_entry = {
        "severity": "CRITICAL",
        "event": "fire_alert",
        "message": "SentialX fire detection alert",
        "event_id": alert["event_id"],
        "customer_id": alert["customer_id"],
        "institution_name": alert.get("institution_name", ""),
        "camera_id": alert["camera_id"],
        "camera_name": alert.get("camera_name", ""),
        "area": alert.get("area", ""),
        "captured_at": alert["captured_at"],
        "detected_at": alert.get("detected_at"),
        "gcs_uri": alert["gcs_uri"],
    }
    print(json.dumps(log_entry, ensure_ascii=False), flush=True)
    return {"status": "notified", "event_id": alert["event_id"]}

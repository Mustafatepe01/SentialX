import base64
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import psycopg2
from fastapi import FastAPI, HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import pubsub_v1, storage
from google.oauth2 import id_token


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("sentialx-frame-worker")

PROJECT_ID = os.environ["PROJECT_ID"]
DB_URL = os.environ["DB_URL"]
PPE_URL = os.environ["PPE_URL"]
FIRE_URL = os.environ["FIRE_URL"]
VLM_URL = os.environ["VLM_URL"]
REPORT_URL = os.environ["REPORT_URL"]
FIRE_TOPIC = os.getenv("FIRE_TOPIC", "fire-alerts")
ANALYSIS_TIMEOUT_SECONDS = float(os.getenv("ANALYSIS_TIMEOUT_SECONDS", "180"))
REPORT_TIMEOUT_SECONDS = float(os.getenv("REPORT_TIMEOUT_SECONDS", "300"))
LOCAL_TIMEZONE = ZoneInfo(os.getenv("LOCAL_TIMEZONE", "Europe/Istanbul"))
SUPABASE_CONFIG = json.loads(os.getenv("SUPABASE_CONFIG", "{}").lstrip("\ufeff"))
SUPABASE_FUNCTION_URL = str(SUPABASE_CONFIG.get("function_url", "")).rstrip("/")
SUPABASE_INGEST_TOKEN = str(SUPABASE_CONFIG.get("ingest_token", ""))
VIOLATION_NAMESPACE = uuid.UUID("f7a2d458-7249-4bc0-9194-88bb317fb975")

storage_client = storage.Client(project=PROJECT_ID)
publisher = pubsub_v1.PublisherClient()
fire_topic_path = publisher.topic_path(PROJECT_ID, FIRE_TOPIC)
app = FastAPI(title="SentialX Frame Worker", version="1.0.0")


@contextmanager
def db_connection():
    connection = psycopg2.connect(DB_URL)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def ensure_schema() -> None:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS frame_events (
                    event_id UUID PRIMARY KEY,
                    schema_version INTEGER NOT NULL,
                    customer_id TEXT NOT NULL,
                    institution_name TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    area TEXT NOT NULL DEFAULT '',
                    captured_at TIMESTAMPTZ NOT NULL,
                    analysis_types JSONB NOT NULL,
                    mode TEXT NOT NULL,
                    frame_count INTEGER NOT NULL,
                    gcs_uri TEXT NOT NULL,
                    status TEXT NOT NULL,
                    detection_results JSONB NOT NULL DEFAULT '{}'::jsonb,
                    report_result JSONB,
                    violation_detected BOOLEAN NOT NULL DEFAULT FALSE,
                    fire_detected BOOLEAN NOT NULL DEFAULT FALSE,
                    fire_alert_message_id TEXT,
                    fire_alert_published_at TIMESTAMPTZ,
                    images_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    images_deleted_at TIMESTAMPTZ,
                    image_deletion_duration_ms INTEGER,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    processed_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE frame_events
                    ADD COLUMN IF NOT EXISTS report_result JSONB,
                    ADD COLUMN IF NOT EXISTS fire_alert_message_id TEXT,
                    ADD COLUMN IF NOT EXISTS fire_alert_published_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS images_deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS images_deleted_at TIMESTAMPTZ,
                    ADD COLUMN IF NOT EXISTS image_deletion_duration_ms INTEGER
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_frame_events_customer_time
                ON frame_events (customer_id, captured_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_frame_events_camera_time
                ON frame_events (camera_id, captured_at DESC)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ppe_shift_violations (
                    violation_id TEXT PRIMARY KEY,
                    event_id UUID NOT NULL REFERENCES frame_events(event_id),
                    customer_id TEXT NOT NULL,
                    institution_name TEXT NOT NULL,
                    camera_id TEXT NOT NULL,
                    camera_name TEXT NOT NULL,
                    area TEXT NOT NULL DEFAULT '',
                    violation_subtype TEXT,
                    confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    frame_url TEXT NOT NULL,
                    captured_at TIMESTAMPTZ NOT NULL,
                    shift_number TEXT NOT NULL,
                    shift_start TIMESTAMPTZ NOT NULL,
                    shift_end TIMESTAMPTZ NOT NULL,
                    report_id TEXT,
                    reported_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ppe_shift_pending
                ON ppe_shift_violations (
                    customer_id, shift_end, captured_at
                )
                WHERE reported_at IS NULL
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ppe_shift_reports (
                    batch_id UUID PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    institution_name TEXT NOT NULL,
                    shift_number TEXT NOT NULL,
                    shift_start TIMESTAMPTZ NOT NULL,
                    shift_end TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL,
                    violation_count INTEGER NOT NULL DEFAULT 0,
                    hourly_distribution JSONB NOT NULL DEFAULT '{}'::jsonb,
                    report_id TEXT,
                    artifact_url TEXT,
                    report_result JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ,
                    UNIQUE (customer_id, shift_start, shift_end)
                )
                """
            )


@app.on_event("startup")
def startup() -> None:
    ensure_schema()
    logger.info("Database schema is ready")


@app.get("/")
@app.get("/health")
def health() -> dict[str, str]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    return {"status": "ok", "service": "sentialx-frame-worker"}


@app.get("/edge/config/{edge_device_id}")
def edge_config(edge_device_id: str) -> dict[str, Any]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    camera_id,
                    customer_id,
                    organization_id,
                    edge_device_id,
                    camera_name,
                    area_name,
                    rtsp_scheme,
                    rtsp_host,
                    rtsp_port,
                    rtsp_path,
                    rtsp_username,
                    credential_key,
                    rtsp_transport,
                    processing_mode,
                    analysis_types,
                    policy_map,
                    motion_threshold,
                    event_window_seconds,
                    top_frames,
                    cooldown_seconds,
                    interval_seconds,
                    jpeg_quality,
                    config_version,
                    metadata,
                    updated_at
                FROM edge_camera_configs
                WHERE edge_device_id = %s
                  AND is_active = TRUE
                ORDER BY rtsp_path, camera_id
                """,
                (edge_device_id,),
            )
            columns = [item.name for item in cursor.description]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    cameras = []
    for row in rows:
        cameras.append(
            {
                **row,
                "camera_id": str(row["camera_id"]),
                "organization_id": (
                    str(row["organization_id"])
                    if row["organization_id"]
                    else None
                ),
                "motion_threshold": float(row["motion_threshold"]),
                "updated_at": row["updated_at"].isoformat(),
            }
        )
    return {
        "edge_device_id": edge_device_id,
        "camera_count": len(cameras),
        "cameras": cameras,
    }


def decode_pubsub_envelope(envelope: dict[str, Any]) -> tuple[dict[str, Any], str]:
    message = envelope.get("message")
    if not isinstance(message, dict) or not message.get("data"):
        raise HTTPException(status_code=400, detail="Pub/Sub message.data is required")

    try:
        event = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Pub/Sub data") from exc

    required = {
        "schema_version",
        "event_id",
        "customer_id",
        "institution_name",
        "camera_id",
        "camera_name",
        "captured_at",
        "analysis_types",
        "mode",
        "frame_count",
        "gcs_uri",
    }
    missing = sorted(required - event.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing event fields: {', '.join(missing)}",
        )
    return event, str(message.get("messageId", "unknown"))


def parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise ValueError("gcs_uri must start with gs://")
    bucket, separator, prefix = gcs_uri[5:].partition("/")
    if not bucket or not separator or not prefix:
        raise ValueError("gcs_uri must include bucket and prefix")
    return bucket, prefix.rstrip("/")


def download_frames(gcs_uri: str) -> list[tuple[str, bytes]]:
    bucket_name, prefix = parse_gcs_uri(gcs_uri)
    blobs = sorted(
        (
            blob
            for blob in storage_client.list_blobs(
                bucket_name,
                prefix=f"{prefix}/frame_",
            )
            if blob.name.lower().endswith((".jpg", ".jpeg", ".png"))
        ),
        key=lambda blob: blob.name,
    )
    if not blobs:
        raise RuntimeError(f"No frames found under {gcs_uri}")
    return [(blob.name.rsplit("/", 1)[-1], blob.download_as_bytes()) for blob in blobs]


def delete_event_images(gcs_uri: str) -> tuple[datetime, int]:
    bucket_name, prefix = parse_gcs_uri(gcs_uri)
    started = time.monotonic()
    blobs = list(storage_client.list_blobs(bucket_name, prefix=f"{prefix}/"))
    for blob in blobs:
        blob.delete()
    deleted_at = datetime.now(timezone.utc)
    duration_ms = round((time.monotonic() - started) * 1000)
    logger.info(
        "Deleted %s GCS objects under %s in %sms",
        len(blobs),
        gcs_uri,
        duration_ms,
    )
    return deleted_at, duration_ms


def normalize_analysis_types(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.split("+")
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError("analysis_types must be a string or list")
    return list(dict.fromkeys(str(item).strip().lower() for item in values if item))


def violation_uuid(event_id: str, analysis_type: str, frame_name: str) -> str:
    return str(
        uuid.uuid5(
            VIOLATION_NAMESPACE,
            f"{event_id}:{analysis_type}:{frame_name}",
        )
    )


def post_supabase_violation(payload: dict[str, Any]) -> None:
    if not SUPABASE_FUNCTION_URL or not SUPABASE_INGEST_TOKEN:
        logger.warning("Supabase ingest is not configured; POST skipped")
        return
    with httpx.Client(timeout=httpx.Timeout(30)) as client:
        response = client.post(
            SUPABASE_FUNCTION_URL,
            headers={
                "x-ingest-token": SUPABASE_INGEST_TOKEN,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


def sync_supabase_violations(
    event: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> int:
    sent = 0
    policy_map = event.get("policy_map") or {}
    for item in results.get("ppe", []):
        response = item["response"]
        if not response.get("ihlal_var"):
            continue
        details = response.get("ihlaller") or {}
        subtypes = list(details.keys()) if isinstance(details, dict) else []
        post_supabase_violation(
            {
                "violation_id": violation_uuid(
                    event["event_id"], "ppe", item["frame"]
                ),
                "camera_id": event["camera_id"],
                "policy_id": int(policy_map.get("ppe", 1)),
                "occurred_at": event["captured_at"],
                "severity": "medium",
                "status": "open",
                "confidence_score": float(response.get("conf_threshold", 0.0)),
                "ai_summary": ", ".join(subtypes) or "PPE ihlali",
                "model_payload": response,
                "snapshot_url": f"{event['gcs_uri']}/{item['frame']}",
                "clip_url": None,
            }
        )
        sent += 1
    for item in results.get("fire", []):
        response = item["response"]
        if not response.get("alert"):
            continue
        post_supabase_violation(
            {
                "violation_id": violation_uuid(
                    event["event_id"], "fire", item["frame"]
                ),
                "camera_id": event["camera_id"],
                "policy_id": int(policy_map.get("fire", 3)),
                "occurred_at": event["captured_at"],
                "severity": "medium",
                "status": "open",
                "confidence_score": float(response.get("olasilik", 0.0)),
                "ai_summary": str(response.get("sinif", "Yangin tespiti")),
                "model_payload": response,
                "snapshot_url": f"{event['gcs_uri']}/{item['frame']}",
                "clip_url": None,
            }
        )
        sent += 1
    return sent


def try_sync_supabase_violations(
    event: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> int:
    try:
        sent = sync_supabase_violations(event, results)
        if sent:
            logger.info(
                "[%s] Supabase POST completed for %s violation(s)",
                event["event_id"],
                sent,
            )
        return sent
    except Exception:
        logger.exception(
            "[%s] Supabase POST failed; primary processing continues",
            event["event_id"],
        )
        return 0


def call_detection(
    client: httpx.Client,
    analysis_type: str,
    frame_name: str,
    frame_bytes: bytes,
) -> dict[str, Any]:
    files = {"file": (frame_name, frame_bytes, "image/jpeg")}
    if analysis_type == "ppe":
        service_url = PPE_URL
        response = client.post(
            service_url,
            files=files,
            headers=cloud_run_auth_headers(service_url),
        )
    elif analysis_type == "fire":
        service_url = FIRE_URL
        response = client.post(
            service_url,
            files=files,
            headers=cloud_run_auth_headers(service_url),
        )
    elif analysis_type == "vlm":
        service_url = VLM_URL
        response = client.post(
            service_url,
            files=files,
            data={"tip": "genel"},
            headers=cloud_run_auth_headers(service_url),
        )
    else:
        raise ValueError(f"Unsupported analysis type: {analysis_type}")
    response.raise_for_status()
    return response.json()


def cloud_run_auth_headers(endpoint_url: str) -> dict[str, str]:
    audience = endpoint_url.split("/", 3)[:3]
    audience_url = "/".join(audience)
    token = id_token.fetch_id_token(GoogleAuthRequest(), audience_url)
    return {"Authorization": f"Bearer {token}"}


def run_primary_detection(
    event: dict[str, Any],
) -> tuple[list[tuple[str, bytes]], dict[str, list[dict[str, Any]]]]:
    frames = download_frames(event["gcs_uri"])
    analysis_types = [
        item
        for item in normalize_analysis_types(event["analysis_types"])
        if item in {"ppe", "fire"}
    ]
    if not analysis_types:
        raise ValueError("At least one primary analysis type (ppe or fire) is required")
    results: dict[str, list[dict[str, Any]]] = {
        analysis_type: [] for analysis_type in analysis_types
    }
    timeout = httpx.Timeout(ANALYSIS_TIMEOUT_SECONDS)
    with httpx.Client(timeout=timeout) as client:
        for frame_name, frame_bytes in frames:
            for analysis_type in analysis_types:
                response = call_detection(
                    client,
                    analysis_type,
                    frame_name,
                    frame_bytes,
                )
                results[analysis_type].append(
                    {"frame": frame_name, "response": response}
                )
    return frames, results


def summarize_primary_results(
    results: dict[str, list[dict[str, Any]]],
) -> tuple[bool, bool]:
    ppe_violation = any(
        bool(item["response"].get("ihlal_var"))
        for item in results.get("ppe", [])
    )
    fire_detected = any(
        bool(item["response"].get("alert"))
        for item in results.get("fire", [])
    )
    return ppe_violation or fire_detected, fire_detected


def run_vlm_analysis(
    frames: list[tuple[str, bytes]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    timeout = httpx.Timeout(ANALYSIS_TIMEOUT_SECONDS)
    with httpx.Client(timeout=timeout) as client:
        for frame_name, frame_bytes in frames:
            response = call_detection(
                client,
                "vlm",
                frame_name,
                frame_bytes,
            )
            results.append({"frame": frame_name, "response": response})
    return results


def vardiya_for(captured_at: datetime) -> tuple[str, datetime, datetime]:
    local_time = captured_at.astimezone(LOCAL_TIMEZONE)
    local_date = local_time.date()
    hour = local_time.hour
    if hour < 8:
        shift = "1"
        start = datetime.combine(local_date, datetime_time(0, 0), LOCAL_TIMEZONE)
    elif hour < 16:
        shift = "2"
        start = datetime.combine(local_date, datetime_time(8, 0), LOCAL_TIMEZONE)
    else:
        shift = "3"
        start = datetime.combine(local_date, datetime_time(16, 0), LOCAL_TIMEZONE)
    return shift, start, start + timedelta(hours=8)


def store_ppe_shift_violations(
    event: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> dict[str, Any] | None:
    captured_at = datetime.fromisoformat(event["captured_at"].replace("Z", "+00:00"))
    shift, shift_start, shift_end = vardiya_for(captured_at)
    violations = []
    for item in results.get("ppe", []):
        response = item["response"]
        if not response.get("ihlal_var"):
            continue
        details = response.get("ihlaller") or {}
        subtypes = list(details.keys()) if isinstance(details, dict) else []
        violations.append(
            {
                "violation_id": f"{event['event_id']}:ppe:{item['frame']}",
                "event_id": event["event_id"],
                "customer_id": event["customer_id"],
                "institution_name": event["institution_name"],
                "camera_id": event["camera_id"],
                "camera_name": event["camera_name"],
                "area": event.get("area", ""),
                "violation_subtype": ", ".join(subtypes) or None,
                "confidence_score": float(response.get("conf_threshold", 0.0)),
                "frame_url": f"{event['gcs_uri']}/{item['frame']}",
                "captured_at": captured_at,
                "shift_number": shift,
                "shift_start": shift_start,
                "shift_end": shift_end,
            }
        )
    if not violations:
        return None

    with db_connection() as connection:
        with connection.cursor() as cursor:
            for violation in violations:
                cursor.execute(
                    """
                    INSERT INTO ppe_shift_violations (
                        violation_id, event_id, customer_id, institution_name,
                        camera_id, camera_name, area, violation_subtype,
                        confidence_score, frame_url, captured_at, shift_number,
                        shift_start, shift_end
                    )
                    VALUES (
                        %(violation_id)s, %(event_id)s, %(customer_id)s,
                        %(institution_name)s, %(camera_id)s, %(camera_name)s,
                        %(area)s, %(violation_subtype)s, %(confidence_score)s,
                        %(frame_url)s, %(captured_at)s, %(shift_number)s,
                        %(shift_start)s, %(shift_end)s
                    )
                    ON CONFLICT (violation_id) DO NOTHING
                    """,
                    violation,
                )
    return {
        "status": "queued_for_shift_report",
        "violation_count": len(violations),
        "shift": shift,
        "shift_start": shift_start.isoformat(),
        "shift_end": shift_end.isoformat(),
    }


def build_report_payload(
    event: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    captured_at = datetime.fromisoformat(event["captured_at"].replace("Z", "+00:00"))
    shift, shift_start, shift_end = vardiya_for(captured_at)
    vlm_results = results.get("vlm", [])
    vlm_description = ""
    vlm_violations: list[str] = []
    if vlm_results:
        vlm_payload = vlm_results[0]["response"].get("sonuc", {})
        vlm_description = str(vlm_payload.get("aciklama", ""))
        vlm_violations = [
            str(item) for item in vlm_payload.get("ihlaller", []) if item
        ]

    violations: list[dict[str, Any]] = []
    for item in results.get("ppe", []):
        response = item["response"]
        if not response.get("ihlal_var"):
            continue
        details = response.get("ihlaller") or {}
        subtypes = list(details.keys()) if isinstance(details, dict) else []
        violations.append(
            {
                "id": f"{event['event_id']}:ppe:{item['frame']}",
                "tesis_id": event["customer_id"],
                "kamera_id": event["camera_id"],
                "kamera_adi": event["camera_name"],
                "ihlal_tipi": "ppe_ihlali",
                "ihlal_alt_tipi": ", ".join(subtypes or vlm_violations) or None,
                "bolge": event.get("area", ""),
                "guven_skoru": float(response.get("conf_threshold", 0.0)),
                "frame_url": f"{event['gcs_uri']}/{item['frame']}",
                "aciklama": vlm_description,
                "tespit_zamani": event["captured_at"],
                "vardiya": shift,
            }
        )
    for item in results.get("fire", []):
        response = item["response"]
        if not response.get("alert"):
            continue
        violations.append(
            {
                "id": f"{event['event_id']}:fire:{item['frame']}",
                "tesis_id": event["customer_id"],
                "kamera_id": event["camera_id"],
                "kamera_adi": event["camera_name"],
                "ihlal_tipi": "yangin",
                "ihlal_alt_tipi": str(response.get("sinif", "yangin")),
                "bolge": event.get("area", ""),
                "guven_skoru": float(response.get("olasilik", 0.0)),
                "frame_url": f"{event['gcs_uri']}/{item['frame']}",
                "aciklama": vlm_description,
                "tespit_zamani": event["captured_at"],
                "vardiya": shift,
            }
        )
    if not violations:
        raise RuntimeError("Violation detected but no report violation could be built")
    return {
        "tesis_id": event["customer_id"],
        "tesis_adi": event["institution_name"],
        "tesis_adresi": None,
        "vardiya": shift,
        "vardiya_baslangic": shift_start.isoformat(),
        "vardiya_bitis": shift_end.isoformat(),
        "sorumlu_isg_uzmani": None,
        "violations": violations,
    }


def create_report(
    event: dict[str, Any],
    results: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    return send_report_payload(build_report_payload(event, results))


def send_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {
        **cloud_run_auth_headers(REPORT_URL),
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=httpx.Timeout(REPORT_TIMEOUT_SECONDS)) as client:
        response = client.post(REPORT_URL, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def claim_due_ppe_shifts(now: datetime) -> list[dict[str, Any]]:
    claimed = []
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    customer_id, institution_name, shift_number,
                    shift_start, shift_end, COUNT(*) AS violation_count
                FROM ppe_shift_violations
                WHERE reported_at IS NULL
                  AND shift_end <= %s
                GROUP BY
                    customer_id, institution_name, shift_number,
                    shift_start, shift_end
                ORDER BY shift_end, customer_id
                """,
                (now,),
            )
            columns = [item.name for item in cursor.description]
            due_shifts = [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]
            for shift in due_shifts:
                batch_id = str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO ppe_shift_reports (
                        batch_id, customer_id, institution_name, shift_number,
                        shift_start, shift_end, status, violation_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'processing', %s)
                    ON CONFLICT (customer_id, shift_start, shift_end)
                    DO NOTHING
                    RETURNING batch_id
                    """,
                    (
                        batch_id,
                        shift["customer_id"],
                        shift["institution_name"],
                        shift["shift_number"],
                        shift["shift_start"],
                        shift["shift_end"],
                        shift["violation_count"],
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    cursor.execute(
                        """
                        UPDATE ppe_shift_reports
                        SET status = 'processing', error = NULL
                        WHERE customer_id = %s
                          AND shift_start = %s
                          AND shift_end = %s
                          AND (
                              status = 'failed'
                              OR (
                                  status = 'processing'
                                  AND created_at < NOW() - INTERVAL '15 minutes'
                              )
                          )
                        RETURNING batch_id
                        """,
                        (
                            shift["customer_id"],
                            shift["shift_start"],
                            shift["shift_end"],
                        ),
                    )
                    row = cursor.fetchone()
                if row is not None:
                    claimed.append({**shift, "batch_id": str(row[0])})
    return claimed


def load_ppe_shift_violations(shift: dict[str, Any]) -> list[dict[str, Any]]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    violation_id, camera_id, camera_name, area,
                    violation_subtype, confidence_score, frame_url,
                    captured_at, shift_number
                FROM ppe_shift_violations
                WHERE customer_id = %s
                  AND shift_start = %s
                  AND shift_end = %s
                  AND reported_at IS NULL
                ORDER BY captured_at, camera_id, violation_id
                """,
                (
                    shift["customer_id"],
                    shift["shift_start"],
                    shift["shift_end"],
                ),
            )
            return [
                {
                    "id": row[0],
                    "tesis_id": shift["customer_id"],
                    "kamera_id": row[1],
                    "kamera_adi": row[2],
                    "ihlal_tipi": "ppe_ihlali",
                    "ihlal_alt_tipi": row[4],
                    "bolge": row[3],
                    "guven_skoru": float(row[5]),
                    "frame_url": row[6],
                    "aciklama": None,
                    "tespit_zamani": row[7].isoformat(),
                    "vardiya": row[8],
                }
                for row in cursor.fetchall()
            ]


def complete_ppe_shift_report(
    shift: dict[str, Any],
    report_result: dict[str, Any],
) -> None:
    report_id = str(report_result["rapor_id"])
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ppe_shift_reports
                SET status = 'completed',
                    violation_count = %s,
                    hourly_distribution = %s::jsonb,
                    report_id = %s,
                    artifact_url = %s,
                    report_result = %s::jsonb,
                    completed_at = NOW(),
                    error = NULL
                WHERE batch_id = %s
                """,
                (
                    report_result["toplam_ihlal"],
                    json.dumps(report_result.get("hourly_distribution", {})),
                    report_id,
                    report_result.get("artifact_url"),
                    json.dumps(report_result, ensure_ascii=False),
                    shift["batch_id"],
                ),
            )
            cursor.execute(
                """
                UPDATE ppe_shift_violations
                SET report_id = %s, reported_at = NOW()
                WHERE customer_id = %s
                  AND shift_start = %s
                  AND shift_end = %s
                  AND reported_at IS NULL
                """,
                (
                    report_id,
                    shift["customer_id"],
                    shift["shift_start"],
                    shift["shift_end"],
                ),
            )


def fail_ppe_shift_report(batch_id: str, error: str) -> None:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ppe_shift_reports
                SET status = 'failed', error = %s
                WHERE batch_id = %s
                """,
                (error[:4000], batch_id),
            )


@app.post("/internal/ppe-shift-reports/run")
def run_ppe_shift_reports() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    claimed = claim_due_ppe_shifts(now)
    completed = []
    failed = []
    for shift in claimed:
        try:
            violations = load_ppe_shift_violations(shift)
            if not violations:
                raise RuntimeError("No pending PPE violations found for shift")
            report_result = send_report_payload(
                {
                    "tesis_id": shift["customer_id"],
                    "tesis_adi": shift["institution_name"],
                    "tesis_adresi": None,
                    "vardiya": shift["shift_number"],
                    "vardiya_baslangic": shift["shift_start"].isoformat(),
                    "vardiya_bitis": shift["shift_end"].isoformat(),
                    "sorumlu_isg_uzmani": None,
                    "violations": violations,
                }
            )
            complete_ppe_shift_report(shift, report_result)
            completed.append(
                {
                    "customer_id": shift["customer_id"],
                    "shift": shift["shift_number"],
                    "report_id": report_result["rapor_id"],
                    "violation_count": report_result["toplam_ihlal"],
                    "hourly_distribution": report_result.get(
                        "hourly_distribution", {}
                    ),
                }
            )
        except Exception as exc:
            fail_ppe_shift_report(shift["batch_id"], str(exc))
            failed.append(
                {
                    "customer_id": shift["customer_id"],
                    "shift": shift["shift_number"],
                    "error": str(exc),
                }
            )
            logger.exception(
                "PPE shift report failed for %s shift %s",
                shift["customer_id"],
                shift["shift_number"],
            )
    response = {
        "status": "completed",
        "claimed": len(claimed),
        "completed": completed,
        "failed": failed,
    }
    if failed:
        raise HTTPException(status_code=500, detail=response)
    return response


def begin_event(event: dict[str, Any]) -> str:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO frame_events (
                    event_id, schema_version, customer_id, institution_name,
                    camera_id, camera_name, area, captured_at, analysis_types,
                    mode, frame_count, gcs_uri, status
                )
                VALUES (
                    %(event_id)s, %(schema_version)s, %(customer_id)s,
                    %(institution_name)s, %(camera_id)s, %(camera_name)s,
                    %(area)s, %(captured_at)s, %(analysis_types)s::jsonb,
                    %(mode)s, %(frame_count)s, %(gcs_uri)s, 'processing'
                )
                ON CONFLICT (event_id) DO NOTHING
                """,
                {
                    **event,
                    "area": event.get("area", ""),
                    "analysis_types": json.dumps(
                        normalize_analysis_types(event["analysis_types"])
                    ),
                },
            )
            cursor.execute(
                "SELECT status FROM frame_events WHERE event_id = %s",
                (event["event_id"],),
            )
            status = cursor.fetchone()[0]
            if status == "failed":
                cursor.execute(
                    """
                    UPDATE frame_events
                    SET status = 'processing', error = NULL
                    WHERE event_id = %s
                    """,
                    (event["event_id"],),
                )
            return status


def complete_event(
    event_id: str,
    results: dict[str, Any],
    violation_detected: bool,
    fire_detected: bool,
    report_result: dict[str, Any] | None = None,
    images_deleted_at: datetime | None = None,
    image_deletion_duration_ms: int | None = None,
) -> None:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE frame_events
                SET status = 'completed',
                    detection_results = %s::jsonb,
                    report_result = %s::jsonb,
                    violation_detected = %s,
                    fire_detected = %s,
                    images_deleted = %s,
                    images_deleted_at = %s,
                    image_deletion_duration_ms = %s,
                    error = NULL,
                    processed_at = NOW()
                WHERE event_id = %s
                """,
                (
                    json.dumps(results, ensure_ascii=False),
                    (
                        json.dumps(report_result, ensure_ascii=False)
                        if report_result is not None
                        else None
                    ),
                    violation_detected,
                    fire_detected,
                    images_deleted_at is not None,
                    images_deleted_at,
                    image_deletion_duration_ms,
                    event_id,
                ),
            )


def fail_event(event_id: str, error: str) -> None:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE frame_events
                SET status = 'failed', error = %s
                WHERE event_id = %s
                """,
                (error[:4000], event_id),
            )


def publish_fire_alert(event: dict[str, Any], results: dict[str, Any]) -> str:
    alert = {
        "schema_version": 1,
        "event_id": event["event_id"],
        "customer_id": event["customer_id"],
        "institution_name": event["institution_name"],
        "camera_id": event["camera_id"],
        "camera_name": event["camera_name"],
        "area": event.get("area", ""),
        "captured_at": event["captured_at"],
        "detected_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "gcs_uri": event["gcs_uri"],
        "fire_results": results.get("fire", []),
    }
    return publisher.publish(
        fire_topic_path,
        json.dumps(alert, ensure_ascii=False).encode("utf-8"),
        event_id=event["event_id"],
        customer_id=event["customer_id"],
        camera_id=event["camera_id"],
    ).result(timeout=30)


def ensure_fire_alert_published(
    event: dict[str, Any],
    results: dict[str, Any],
) -> tuple[str, bool]:
    with db_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT fire_alert_message_id
                FROM frame_events
                WHERE event_id = %s
                FOR UPDATE
                """,
                (event["event_id"],),
            )
            existing_message_id = cursor.fetchone()[0]
            if existing_message_id:
                return str(existing_message_id), False

            message_id = publish_fire_alert(event, results)
            cursor.execute(
                """
                UPDATE frame_events
                SET fire_alert_message_id = %s,
                    fire_alert_published_at = NOW()
                WHERE event_id = %s
                """,
                (message_id, event["event_id"]),
            )
            return message_id, True


@app.post("/pubsub/frame")
async def process_pubsub(request: Request) -> dict[str, Any]:
    envelope = await request.json()
    event, message_id = decode_pubsub_envelope(envelope)
    event_id = event["event_id"]
    previous_status = begin_event(event)
    if previous_status == "completed":
        logger.info("[%s] Duplicate message acknowledged: %s", event_id, message_id)
        return {"status": "duplicate", "event_id": event_id}

    try:
        frames, results = run_primary_detection(event)
        violation_detected, fire_detected = summarize_primary_results(results)
        if not violation_detected:
            images_deleted_at, deletion_duration_ms = delete_event_images(
                event["gcs_uri"]
            )
            complete_event(
                event_id,
                results,
                False,
                False,
                images_deleted_at=images_deleted_at,
                image_deletion_duration_ms=deletion_duration_ms,
            )
            logger.info(
                "[%s] No violation; images deleted and event completed",
                event_id,
            )
            return {
                "status": "completed",
                "event_id": event_id,
                "violation_detected": False,
                "images_deleted": True,
                "image_deletion_duration_ms": deletion_duration_ms,
            }

        fire_message_id = None
        if fire_detected:
            fire_message_id, was_published = ensure_fire_alert_published(
                event,
                results,
            )
            log_method = logger.warning if was_published else logger.info
            log_method(
                "[%s] Fire alert %s: %s",
                event_id,
                "published" if was_published else "already published",
                fire_message_id,
            )

        ppe_shift_result = store_ppe_shift_violations(event, results)
        if not fire_detected:
            supabase_sent = try_sync_supabase_violations(event, results)
            results["vlm"] = []
            complete_event(
                event_id,
                results,
                True,
                False,
                report_result=ppe_shift_result,
            )
            logger.info(
                "[%s] PPE violations queued for shift report",
                event_id,
            )
            return {
                "status": "completed",
                "event_id": event_id,
                "violation_detected": True,
                "fire_detected": False,
                "ppe_shift_report": ppe_shift_result,
                "supabase_posted": supabase_sent,
            }

        try:
            results["vlm"] = run_vlm_analysis(frames)
        except Exception as exc:
            logger.warning(
                "[%s] VLM analizi kullanılamadı; ana analiz sonuçlarıyla devam ediliyor: %s",
                event_id,
                exc,
            )
            results["vlm"] = []
        report_result = create_report(event, results)
        supabase_sent = try_sync_supabase_violations(event, results)
        complete_event(
            event_id,
            results,
            True,
            fire_detected,
            report_result=report_result,
        )
        logger.info("[%s] Event completed from message %s", event_id, message_id)
        return {
            "status": "completed",
            "event_id": event_id,
            "violation_detected": violation_detected,
            "fire_detected": fire_detected,
            "fire_alert_message_id": fire_message_id,
            "report_id": report_result.get("rapor_id"),
            "ppe_shift_report": ppe_shift_result,
            "supabase_posted": supabase_sent,
        }
    except Exception as exc:
        logger.exception("[%s] Event processing failed", event_id)
        fail_event(event_id, str(exc))
        raise HTTPException(status_code=500, detail="Event processing failed") from exc

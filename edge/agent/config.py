import json
import logging
from pathlib import Path
from urllib.parse import quote

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import AuthorizedSession


ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = ROOT / "settings.json"
CAMERAS_PATH = ROOT / "cameras.json"
SECRETS_PATH = ROOT / "secrets.local.json"
OUTBOX_PATH = ROOT / "buffer" / "outbox"
QUARANTINE_PATH = ROOT / "buffer" / "quarantine"
TEMP_PATH = ROOT / "buffer" / "temp"
LOG_PATH = ROOT / "logs" / "edge-agent.log"
logger = logging.getLogger(__name__)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def fetch_camera_config(settings: dict) -> dict:
    base_url = settings["config_api_url"].rstrip("/")
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    source_credentials, _ = google.auth.default(scopes=scopes)
    target_credentials = impersonated_credentials.Credentials(
        source_credentials=source_credentials,
        target_principal=settings["edge_service_account"],
        target_scopes=scopes,
        lifetime=3600,
    )
    id_credentials = impersonated_credentials.IDTokenCredentials(
        target_credentials=target_credentials,
        target_audience=base_url,
        include_email=True,
    )
    session = AuthorizedSession(id_credentials)
    response = session.get(
        f"{base_url}/edge/config/{settings['edge_device_id']}",
        timeout=float(settings.get("config_timeout_seconds", 20)),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("cameras"):
        raise ValueError(
            f"{settings['edge_device_id']} icin aktif kamera bulunamadi"
        )
    return payload


def normalize_cameras(camera_data: dict, secrets: dict) -> list[dict]:
    credentials = secrets.get("credentials", {})
    cameras = []
    for source in camera_data.get("cameras", []):
        credential_key = source.get("credential_key", "mediamtx-default")
        credential = credentials.get(credential_key)
        if not credential:
            raise ValueError(
                f"Eksik yerel credential: {credential_key}"
            )
        username = quote(
            source.get("rtsp_username")
            or credential.get("username", "sentialx"),
            safe="",
        )
        password = quote(credential["password"], safe="")
        camera = {
            "id": str(source.get("camera_id") or source.get("id")),
            "name": source.get("camera_name") or source.get("name"),
            "area": source.get("area_name") or source.get("area", ""),
            "host": source.get("rtsp_host") or source.get("host"),
            "port": source.get("rtsp_port") or source.get("port", 8554),
            "path": source.get("rtsp_path") or source.get("path"),
            "mode": source.get("processing_mode") or source.get("mode"),
            "analysis_types": source["analysis_types"],
            "motion_threshold": float(
                source.get("motion_threshold", 0.03)
            ),
            "event_window_seconds": int(
                source.get("event_window_seconds", 5)
            ),
            "top_frames": int(source.get("top_frames", 3)),
            "cooldown_seconds": int(source.get("cooldown_seconds", 10)),
            "interval_seconds": int(source.get("interval_seconds", 10)),
            "jpeg_quality": int(source.get("jpeg_quality", 88)),
            "policy_map": source.get("policy_map", {}),
            "config_version": int(source.get("config_version", 1)),
        }
        scheme = source.get("rtsp_scheme", "rtsp")
        camera["url"] = (
            f"{scheme}://{username}:{password}@{camera['host']}:"
            f"{camera['port']}/{camera['path']}"
        )
        cameras.append(camera)
    return cameras


def load_config() -> tuple[dict, list[dict]]:
    settings = read_json(SETTINGS_PATH)
    secrets = read_json(SECRETS_PATH)

    required_settings = (
        "customer_id",
        "project_id",
        "bucket",
        "pubsub_topic",
        "edge_device_id",
        "config_api_url",
        "edge_service_account",
    )
    missing = [key for key in required_settings if not settings.get(key)]
    if missing:
        raise ValueError(f"Eksik settings alanlari: {', '.join(missing)}")

    try:
        camera_data = fetch_camera_config(settings)
        write_json_atomic(CAMERAS_PATH, camera_data)
        logger.info(
            "Kamera ayarlari cloud API'den alindi: %s",
            len(camera_data["cameras"]),
        )
    except Exception as exc:
        if not CAMERAS_PATH.exists():
            raise RuntimeError(
                f"Cloud config alinamadi ve yerel cache yok: {exc}"
            ) from exc
        logger.warning(
            "Cloud config alinamadi, yerel cache kullaniliyor: %s",
            exc,
        )
        camera_data = read_json(CAMERAS_PATH)

    cameras = normalize_cameras(camera_data, secrets)
    if not cameras:
        raise ValueError("Aktif kamera bulunamadi")

    seen_ids = set()
    for camera in cameras:
        camera_id = camera.get("id")
        if not camera_id or camera_id in seen_ids:
            raise ValueError(f"Gecersiz veya tekrar eden kamera id: {camera_id}")
        seen_ids.add(camera_id)
        if camera.get("mode") not in {"motion", "interval"}:
            raise ValueError(f"{camera_id}: mode motion veya interval olmali")
        if not camera.get("analysis_types"):
            raise ValueError(f"{camera_id}: analysis_types bos olamaz")

    OUTBOX_PATH.mkdir(parents=True, exist_ok=True)
    QUARANTINE_PATH.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    return settings, cameras

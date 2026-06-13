import json
import logging
import os
import shutil
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


logger = logging.getLogger(__name__)


def create_event(
    outbox_path: Path,
    customer_id: str,
    institution_name: str,
    camera: dict,
    frames: list,
    jpeg_quality: int,
) -> Path:
    event_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    temporary = outbox_path / f".{event_id}.tmp"
    final = outbox_path / event_id
    temporary.mkdir(parents=True, exist_ok=False)

    from vision import blur_faces, save_jpeg

    frame_names = []
    for index, frame in enumerate(frames):
        frame_name = f"frame_{index:02d}.jpg"
        save_jpeg(blur_faces(frame.copy()), temporary / frame_name, jpeg_quality)
        frame_names.append(frame_name)

    event = {
        "schema_version": 1,
        "event_id": event_id,
        "customer_id": customer_id,
        "institution_name": institution_name,
        "camera_id": camera["id"],
        "camera_name": camera.get("name", camera["id"]),
        "area": camera.get("area", ""),
        "captured_at": created_at,
        "analysis_types": camera["analysis_types"],
        "policy_map": camera.get("policy_map", {}),
        "mode": camera["mode"],
        "frame_count": len(frame_names),
        "frames": frame_names,
        "gcs_uploaded": False,
        "published": False,
    }
    (temporary / "event.json").write_text(
        json.dumps(event, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.rename(final)
    logger.info("[%s] Outbox olayi olusturuldu: %s", camera["id"], event_id)
    return final


def delete_event(path: Path) -> None:
    def remove_readonly(function, target, _error_info):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    last_error = None
    for attempt in range(5):
        if not path.exists():
            return
        try:
            shutil.rmtree(path, onerror=remove_readonly)
            return
        except OSError as exc:
            last_error = exc
            try:
                path.rmdir()
                return
            except OSError:
                time.sleep(0.2 * (attempt + 1))
    if last_error is not None:
        raise last_error

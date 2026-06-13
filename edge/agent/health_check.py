import json

import config
from vision import open_camera, read_frame


def check_camera(camera: dict) -> dict:
    capture = None
    frame = None
    error = None
    try:
        capture = open_camera(camera["url"], camera["id"])
        frame = read_frame(capture)
    except Exception as exc:
        error = str(exc)
    finally:
        if capture is not None:
            capture.close()
    result = {
        "camera_id": camera["id"],
        "mode": camera["mode"],
        "healthy": frame is not None,
    }
    if frame is not None:
        result["resolution"] = f"{frame.shape[1]}x{frame.shape[0]}"
    if error:
        result["error"] = error
    return result


def main() -> int:
    settings, cameras = config.load_config()
    results = [check_camera(camera) for camera in cameras]
    pending = [
        path
        for path in config.OUTBOX_PATH.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    output = {
        "status": "ok" if all(item["healthy"] for item in results) else "warning",
        "project_id": settings["project_id"],
        "bucket": settings["bucket"],
        "pubsub_topic": settings["pubsub_topic"],
        "cameras": results,
        "pending_outbox_packages": len(pending),
    }
    print(json.dumps(output, ensure_ascii=True, indent=2))
    return 0 if output["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())

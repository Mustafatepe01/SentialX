import json
import logging
import shutil
import signal
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

import cv2

import config
from cloud_sender import CloudSender
from outbox import create_event, delete_event
from vision import open_camera, read_frame


stop_event = threading.Event()


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            RotatingFileHandler(
                config.LOG_PATH,
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )


def outbox_size_gb() -> float:
    size = sum(
        item.stat().st_size
        for item in config.OUTBOX_PATH.rglob("*")
        if item.is_file()
    )
    return size / 1024**3


def store_event(settings: dict, camera: dict, frames: list) -> None:
    if outbox_size_gb() >= float(settings.get("max_outbox_gb", 10)):
        logging.error("[%s] Outbox limiti dolu, olay atlandi", camera["id"])
        return
    create_event(
        config.OUTBOX_PATH,
        settings["customer_id"],
        settings.get("institution_name", settings["customer_id"]),
        camera,
        frames,
        int(camera.get("jpeg_quality", settings.get("jpeg_quality", 88))),
    )


def motion_worker(settings: dict, camera: dict) -> None:
    logger = logging.getLogger(__name__)
    retry = float(settings.get("camera_retry_seconds", 10))
    while not stop_event.is_set():
        capture = None
        try:
            capture = open_camera(camera["url"], camera["id"])
            subtractor = cv2.createBackgroundSubtractorMOG2(
                history=300,
                varThreshold=20,
                detectShadows=False,
            )
            threshold = float(camera.get("motion_threshold", 0.03))
            window_seconds = float(camera.get("event_window_seconds", 5))
            top_n = int(camera.get("top_frames", 3))
            cooldown = float(camera.get("cooldown_seconds", 10))
            last_event = 0.0
            collecting_until = None
            candidates = []

            while not stop_event.is_set():
                frame = read_frame(capture)
                mask = subtractor.apply(frame)
                score = float(mask.mean() / 255.0)
                now = time.monotonic()

                if (
                    collecting_until is None
                    and score >= threshold
                    and now - last_event >= cooldown
                ):
                    collecting_until = now + window_seconds
                    candidates = []
                    logger.info("[%s] Hareket algilandi", camera["id"])

                if collecting_until is not None:
                    candidates.append((score, frame.copy()))
                    if now >= collecting_until:
                        frames = [
                            item[1]
                            for item in sorted(
                                candidates,
                                key=lambda item: item[0],
                                reverse=True,
                            )[:top_n]
                        ]
                        if frames:
                            store_event(settings, camera, frames)
                        last_event = now
                        collecting_until = None
                        candidates = []
        except Exception as exc:
            logger.error("[%s] Kamera hatasi: %s", camera["id"], exc)
            stop_event.wait(retry)
        finally:
            if capture is not None:
                capture.close()


def interval_worker(settings: dict, camera: dict) -> None:
    logger = logging.getLogger(__name__)
    retry = float(settings.get("camera_retry_seconds", 10))
    interval = float(camera.get("interval_seconds", 10))
    while not stop_event.is_set():
        capture = None
        try:
            capture = open_camera(camera["url"], camera["id"])
            while not stop_event.is_set():
                frame = read_frame(capture)
                store_event(settings, camera, [frame])
                stop_event.wait(interval)
        except Exception as exc:
            logger.error("[%s] Kamera hatasi: %s", camera["id"], exc)
            stop_event.wait(retry)
        finally:
            if capture is not None:
                capture.close()


def package_send_priority(package: Path) -> tuple[int, str]:
    try:
        event = json.loads(
            (package / "event.json").read_text(encoding="utf-8")
        )
        analysis_types = {
            str(item).strip().lower()
            for item in event.get("analysis_types", [])
        }
        fire_priority = 0 if "fire" in analysis_types else 1
        return fire_priority, str(event.get("captured_at", package.name))
    except (OSError, ValueError, TypeError):
        return 2, package.name


def sender_worker(settings: dict) -> None:
    logger = logging.getLogger(__name__)
    sender = CloudSender(settings)
    retry = float(settings.get("retry_seconds", 30))
    while not stop_event.is_set():
        packages = sorted(
            (
                path
                for path in config.OUTBOX_PATH.iterdir()
                if path.is_dir() and not path.name.startswith(".")
            ),
            key=package_send_priority,
        )
        if not packages:
            stop_event.wait(1)
            continue
        for package in packages:
            if stop_event.is_set():
                break
            try:
                event_path = package / "event.json"
                if not event_path.exists():
                    try:
                        delete_event(package)
                    except OSError as exc:
                        logger.warning(
                            "[%s] Bos yerel klasor temizligi bekliyor: %s",
                            package.name,
                            exc,
                        )
                    continue
                event = json.loads(
                    event_path.read_text(encoding="utf-8")
                )
                try:
                    uuid.UUID(str(event.get("camera_id", "")))
                except ValueError:
                    destination = config.QUARANTINE_PATH / package.name
                    if destination.exists():
                        destination = config.QUARANTINE_PATH / (
                            f"{package.name}-{int(time.time())}"
                        )
                    package.replace(destination)
                    logger.warning(
                        "[%s] UUID olmayan eski kamera paketi karantinaya alindi",
                        package.name,
                    )
                    continue
                sender.send(package)
            except Exception as exc:
                logger.warning(
                    "[%s] Cloud gonderimi bekliyor: %s",
                    package.name,
                    exc,
                )
                sender.reset()
                stop_event.wait(retry)
                break


def shutdown(*_args) -> None:
    stop_event.set()


def main() -> int:
    settings, cameras = config.load_config()
    setup_logging()
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    disk = shutil.disk_usage(config.ROOT)
    if disk.free < 1024**3:
        raise RuntimeError("Edge diski icin 1 GB'den az bos alan kaldi")

    threads = [
        threading.Thread(
            target=sender_worker,
            args=(settings,),
            name="cloud-sender",
            daemon=True,
        )
    ]
    for camera in cameras:
        target = motion_worker if camera["mode"] == "motion" else interval_worker
        threads.append(
            threading.Thread(
                target=target,
                args=(settings, camera),
                name=camera["id"],
                daemon=True,
            )
        )

    for thread in threads:
        thread.start()

    logging.info(
        "Edge Agent basladi: %s",
        ", ".join(camera["id"] for camera in cameras),
    )
    while not stop_event.wait(1):
        dead = [thread.name for thread in threads if not thread.is_alive()]
        if dead:
            raise RuntimeError(f"Thread durdu: {', '.join(dead)}")
    logging.info("Edge Agent durduruldu")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

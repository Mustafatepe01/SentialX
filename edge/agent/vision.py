import logging
import queue
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np


logger = logging.getLogger(__name__)
FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


class FFmpegCamera:
    def __init__(self, url: str, camera_id: str):
        self.camera_id = camera_id
        self.frames = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-rtsp_transport",
                "tcp",
                "-i",
                url,
                "-an",
                "-c:v",
                "mjpeg",
                "-q:v",
                "5",
                "-f",
                "image2pipe",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            creationflags=creation_flags,
        )
        self.reader = threading.Thread(
            target=self._read_loop,
            name=f"{camera_id}-ffmpeg-reader",
            daemon=True,
        )
        self.reader.start()

    def _read_loop(self) -> None:
        buffer = bytearray()
        while not self.closed.is_set() and self.process.poll() is None:
            chunk = self.process.stdout.read(65536)
            if not chunk:
                break
            buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xff\xd8")
                end = buffer.find(b"\xff\xd9", start + 2)
                if start < 0 or end < 0:
                    if len(buffer) > 10 * 1024 * 1024:
                        buffer.clear()
                    break
                jpeg = bytes(buffer[start : end + 2])
                del buffer[: end + 2]
                frame = cv2.imdecode(
                    np.frombuffer(jpeg, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                if frame is None:
                    continue
                try:
                    self.frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.frames.put_nowait(frame)
                except queue.Full:
                    pass

    def read(self, timeout: float = 10):
        if self.process.poll() is not None:
            raise RuntimeError(
                f"{self.camera_id}: FFmpeg beklenmedik sekilde durdu"
            )
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError(
                f"{self.camera_id}: 10 saniye icinde frame gelmedi"
            ) from exc

    def close(self) -> None:
        self.closed.set()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


def open_camera(url: str, camera_id: str) -> FFmpegCamera:
    camera = FFmpegCamera(url, camera_id)
    try:
        camera.read(timeout=10)
    except Exception:
        camera.close()
        raise
    logger.info("[%s] RTSP baglantisi kuruldu", camera_id)
    return camera


def read_frame(capture: FFmpegCamera):
    return capture.read(timeout=10)


def blur_faces(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=4,
        minSize=(30, 30),
    )
    for x, y, width, height in faces:
        region = frame[y : y + height, x : x + width]
        frame[y : y + height, x : x + width] = cv2.GaussianBlur(
            region,
            (99, 99),
            30,
        )
    return frame


def save_jpeg(frame, path: Path, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(
        str(path),
        frame,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        raise RuntimeError(f"JPEG yazilamadi: {path}")


def wait_for_frame(capture: FFmpegCamera, stop_event, seconds: float):
    deadline = time.monotonic() + seconds
    latest = None
    while not stop_event.is_set() and time.monotonic() < deadline:
        latest = read_frame(capture)
    return latest

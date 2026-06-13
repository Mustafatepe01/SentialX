from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from models import ReportRequest, ReportResponse

try:
    import redis.asyncio as redis_asyncio
except Exception:  # pragma: no cover - optional dependency
    redis_asyncio = None

try:
    from google.cloud import storage
except Exception:  # pragma: no cover - optional dependency
    storage = None

logger = logging.getLogger(__name__)


class BaseQueueStore:
    backend_name = "base"

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def submit(self, request: ReportRequest) -> str:
        raise NotImplementedError

    async def next_job_id(self) -> Optional[str]:
        raise NotImplementedError

    async def get_job(self, job_id: str) -> Optional[dict]:
        raise NotImplementedError

    async def list_jobs(self) -> list[dict]:
        raise NotImplementedError

    async def delete_job(self, job_id: str) -> bool:
        raise NotImplementedError

    async def mark_processing(self, job_id: str) -> None:
        raise NotImplementedError

    async def mark_completed(self, job_id: str, result: ReportResponse) -> None:
        raise NotImplementedError

    async def mark_failed(self, job_id: str, error: str) -> None:
        raise NotImplementedError


class FileQueueStore(BaseQueueStore):
    backend_name = "file"

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.jobs: dict[str, dict[str, Any]] = {}
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        await self._load()

    async def close(self) -> None:
        await self._persist()

    async def submit(self, request: ReportRequest) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now()
        async with self.lock:
            self.jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "message": "Rapor kuyruğa alındı",
                "error": None,
                "request": request,
                "result": None,
                "created_at": now,
                "updated_at": now,
            }
            await self.queue.put(job_id)
            await self._persist()
        return job_id

    async def next_job_id(self) -> Optional[str]:
        return await self.queue.get()

    async def get_job(self, job_id: str) -> Optional[dict]:
        async with self.lock:
            job = self.jobs.get(job_id)
            return self._clone_job(job) if job else None

    async def list_jobs(self) -> list[dict]:
        async with self.lock:
            items = [
                self._clone_job(job)
                for job in sorted(
                    self.jobs.values(),
                    key=lambda item: item["created_at"],
                    reverse=True,
                )
                if job.get("status") != "deleted"
            ]
        return items

    async def delete_job(self, job_id: str) -> bool:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False

            if job.get("status") == "deleted":
                return True

            if job.get("status") == "queued":
                job["status"] = "deleted"
                job["message"] = "İş silindi"
                job["updated_at"] = datetime.now()
            elif job.get("status") == "processing":
                job["status"] = "deleted"
                job["message"] = "İş silindi; çalışan görev arka planda tamamlanabilir"
                job["updated_at"] = datetime.now()
            else:
                job["status"] = "deleted"
                job["message"] = "İş silindi"
                job["updated_at"] = datetime.now()
            await self._persist()
        return True

    async def mark_processing(self, job_id: str) -> None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") == "deleted":
                return
            job["status"] = "processing"
            job["message"] = "Rapor işleniyor"
            job["updated_at"] = datetime.now()
            await self._persist()

    async def mark_completed(self, job_id: str, result: ReportResponse) -> None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") == "deleted":
                return
            job["result"] = result
            job["status"] = "completed"
            job["message"] = "Rapor tamamlandı"
            job["error"] = None
            job["updated_at"] = datetime.now()
            await self._persist()

    async def mark_failed(self, job_id: str, error: str) -> None:
        async with self.lock:
            job = self.jobs.get(job_id)
            if not job or job.get("status") == "deleted":
                return
            job["status"] = "failed"
            job["message"] = "Rapor üretilemedi"
            job["error"] = error
            job["updated_at"] = datetime.now()
            await self._persist()

    async def _load(self) -> None:
        if not self.state_file.exists():
            return

        with self.state_file.open("r", encoding="utf-8") as file_handle:
            raw_jobs = json.load(file_handle)

        async with self.lock:
            for job_id, job in raw_jobs.items():
                request = ReportRequest.model_validate(job["request"])
                result = ReportResponse.model_validate(job["result"]) if job.get("result") else None
                self.jobs[job_id] = {
                    "job_id": job["job_id"],
                    "status": job["status"],
                    "message": job.get("message"),
                    "error": job.get("error"),
                    "request": request,
                    "result": result,
                    "created_at": datetime.fromisoformat(job["created_at"]),
                    "updated_at": datetime.fromisoformat(job["updated_at"]),
                }
                if self.jobs[job_id]["status"] in {"queued", "processing"}:
                    self.jobs[job_id]["status"] = "queued"
                    self.jobs[job_id]["message"] = "Rapor kuyruğa alındı"
                    await self.queue.put(job_id)

    async def _persist(self) -> None:
        payload = {
            job_id: self._serialize_job(job)
            for job_id, job in self.jobs.items()
        }

        if not payload:
            if self.state_file.exists():
                self.state_file.unlink()
            return

        temp_file = self.state_file.with_suffix(".tmp")
        with temp_file.open("w", encoding="utf-8") as file_handle:
            json.dump(payload, file_handle, ensure_ascii=False, indent=2)
        temp_file.replace(self.state_file)

    @staticmethod
    def _serialize_job(job: dict) -> dict:
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "message": job.get("message"),
            "error": job.get("error"),
            "request": job["request"].model_dump(mode="json"),
            "result": job["result"].model_dump(mode="json") if job.get("result") else None,
            "created_at": job["created_at"].isoformat(),
            "updated_at": job["updated_at"].isoformat(),
        }

    @staticmethod
    def _clone_job(job: Optional[dict]) -> Optional[dict]:
        if not job:
            return None
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "message": job.get("message"),
            "error": job.get("error"),
            "request": job["request"],
            "result": job.get("result"),
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }


class RedisQueueStore(BaseQueueStore):
    backend_name = "redis"

    def __init__(self, redis_url: str, prefix: str):
        if redis_asyncio is None:
            raise RuntimeError("redis package is not installed")

        self.redis = redis_asyncio.Redis.from_url(redis_url, decode_responses=True)
        self.prefix = prefix
        self.queue_key = f"{prefix}:pending"
        self.index_key = f"{prefix}:index"
        self.job_key_prefix = f"{prefix}:job:"

    async def initialize(self) -> None:
        await self.redis.ping()

    async def close(self) -> None:
        await self.redis.aclose()

    async def submit(self, request: ReportRequest) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now()
        job_key = self._job_key(job_id)
        await self.redis.hset(
            job_key,
            mapping={
                "job_id": job_id,
                "status": "queued",
                "message": "Rapor kuyruğa alındı",
                "error": "",
                "request": request.model_dump_json(),
                "result": "",
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
            },
        )
        await self.redis.zadd(self.index_key, {job_id: now.timestamp()})
        await self.redis.rpush(self.queue_key, job_id)
        return job_id

    async def next_job_id(self) -> Optional[str]:
        result = await self.redis.blpop(self.queue_key, timeout=1)
        if not result:
            return None
        return result[1]

    async def get_job(self, job_id: str) -> Optional[dict]:
        payload = await self.redis.hgetall(self._job_key(job_id))
        if not payload:
            return None
        return self._deserialize_job(payload)

    async def list_jobs(self) -> list[dict]:
        job_ids = await self.redis.zrevrange(self.index_key, 0, -1)
        if not job_ids:
            return []

        pipeline = self.redis.pipeline()
        for job_id in job_ids:
            pipeline.hgetall(self._job_key(job_id))
        raw_jobs = await pipeline.execute()

        items: list[dict] = []
        for raw_job in raw_jobs:
            if not raw_job:
                continue
            job = self._deserialize_job(raw_job)
            if job["status"] == "deleted":
                continue
            items.append(job)
        return items

    async def delete_job(self, job_id: str) -> bool:
        job_key = self._job_key(job_id)
        payload = await self.redis.hgetall(job_key)
        if not payload:
            return False

        status = payload.get("status", "")
        if status == "queued":
            await self.redis.lrem(self.queue_key, 0, job_id)

        now = datetime.now().isoformat()
        message = "İş silindi"
        if status == "processing":
            message = "İş silindi; çalışan görev arka planda tamamlanabilir"

        await self.redis.hset(
            job_key,
            mapping={
                "status": "deleted",
                "message": message,
                "updated_at": now,
            },
        )
        return True

    async def mark_processing(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        await self.redis.hset(
            self._job_key(job_id),
            mapping={
                "status": "processing",
                "message": "Rapor işleniyor",
                "updated_at": datetime.now().isoformat(),
            },
        )

    async def mark_completed(self, job_id: str, result: ReportResponse) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        await self.redis.hset(
            self._job_key(job_id),
            mapping={
                "status": "completed",
                "message": "Rapor tamamlandı",
                "error": "",
                "result": result.model_dump_json(),
                "updated_at": datetime.now().isoformat(),
            },
        )

    async def mark_failed(self, job_id: str, error: str) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        await self.redis.hset(
            self._job_key(job_id),
            mapping={
                "status": "failed",
                "message": "Rapor üretilemedi",
                "error": error,
                "updated_at": datetime.now().isoformat(),
            },
        )

    def _job_key(self, job_id: str) -> str:
        return f"{self.job_key_prefix}{job_id}"

    @staticmethod
    def _deserialize_job(payload: dict[str, Any]) -> dict:
        request = ReportRequest.model_validate_json(payload["request"])
        result = ReportResponse.model_validate_json(payload["result"]) if payload.get("result") else None
        return {
            "job_id": payload["job_id"],
            "status": payload["status"],
            "message": payload.get("message") or None,
            "error": payload.get("error") or None,
            "request": request,
            "result": result,
            "created_at": datetime.fromisoformat(payload["created_at"]),
            "updated_at": datetime.fromisoformat(payload["updated_at"]),
        }


class GCSQueueStore(BaseQueueStore):
    backend_name = "gcs"

    def __init__(self, bucket_name: str, prefix: str):
        if storage is None:
            raise RuntimeError("google-cloud-storage package is not installed")

        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)
        self.queue_blob_name = self._name("queue", "pending.json")
        self.jobs_prefix = self._name("jobs")
        self.lock = asyncio.Lock()
        self.queue: list[str] = []

    async def initialize(self) -> None:
        if not self.bucket.exists():
            raise RuntimeError(f"GCS bucket not found: {self.bucket_name}")
        await self._load_queue()

    async def close(self) -> None:
        await self._persist_queue()

    async def submit(self, request: ReportRequest) -> str:
        job_id = str(uuid.uuid4())
        now = datetime.now()
        job = {
            "job_id": job_id,
            "status": "queued",
            "message": "Rapor kuyruğa alındı",
            "error": None,
            "request": request,
            "result": None,
            "created_at": now,
            "updated_at": now,
        }
        async with self.lock:
            await self._write_job(job)
            self.queue.append(job_id)
            await self._persist_queue()
        return job_id

    async def next_job_id(self) -> Optional[str]:
        async with self.lock:
            if not self.queue:
                await self._load_queue()
            if not self.queue:
                return None
            job_id = self.queue.pop(0)
            await self._persist_queue()
            return job_id

    async def get_job(self, job_id: str) -> Optional[dict]:
        blob = self.bucket.blob(self._job_name(job_id))
        if not blob.exists():
            return None
        payload = json.loads(blob.download_as_text())
        return self._deserialize_job(payload)

    async def list_jobs(self) -> list[dict]:
        items = []
        for blob in self.client.list_blobs(self.bucket, prefix=self.jobs_prefix):
            payload = json.loads(blob.download_as_text())
            job = self._deserialize_job(payload)
            if job["status"] != "deleted":
                items.append(job)
        items.sort(key=lambda item: item["created_at"], reverse=True)
        return items

    async def delete_job(self, job_id: str) -> bool:
        job = await self.get_job(job_id)
        if not job:
            return False

        async with self.lock:
            if job_id in self.queue:
                self.queue = [item for item in self.queue if item != job_id]
                await self._persist_queue()

        if job.get("status") == "processing":
            job["status"] = "deleted"
            job["message"] = "İş silindi; çalışan görev arka planda tamamlanabilir"
        else:
            job["status"] = "deleted"
            job["message"] = "İş silindi"

        job["updated_at"] = datetime.now()
        await self._write_job(job)
        return True

    async def mark_processing(self, job_id: str) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        job["status"] = "processing"
        job["message"] = "Rapor işleniyor"
        job["updated_at"] = datetime.now()
        await self._write_job(job)

    async def mark_completed(self, job_id: str, result: ReportResponse) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        job["result"] = result
        job["status"] = "completed"
        job["message"] = "Rapor tamamlandı"
        job["error"] = None
        job["updated_at"] = datetime.now()
        await self._write_job(job)

    async def mark_failed(self, job_id: str, error: str) -> None:
        job = await self.get_job(job_id)
        if not job or job["status"] == "deleted":
            return
        job["status"] = "failed"
        job["message"] = "Rapor üretilemedi"
        job["error"] = error
        job["updated_at"] = datetime.now()
        await self._write_job(job)

    def _job_name(self, job_id: str) -> str:
        return self._name("jobs", f"{job_id}.json")

    def _name(self, *parts: str) -> str:
        clean_parts = [part.strip("/") for part in parts if part]
        return "/".join([self.prefix, *clean_parts]) if self.prefix else "/".join(clean_parts)

    async def _write_job(self, job: dict) -> None:
        blob = self.bucket.blob(self._job_name(job["job_id"]))
        blob.upload_from_string(
            json.dumps(self._serialize_job(job), ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )

    async def _load_queue(self) -> None:
        blob = self.bucket.blob(self.queue_blob_name)
        if not blob.exists():
            self.queue = []
            return

        payload = json.loads(blob.download_as_text())
        self.queue = payload.get("pending", [])

    async def _persist_queue(self) -> None:
        blob = self.bucket.blob(self.queue_blob_name)
        blob.upload_from_string(
            json.dumps({"pending": self.queue}, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )


async def build_queue_store(queue_backend: str, redis_url: str, state_file: Path, redis_prefix: str) -> BaseQueueStore:
    backend = queue_backend.lower().strip()
    if backend not in {"auto", "redis", "file"}:
        backend = "auto"

    if backend in {"auto", "redis"} and redis_asyncio is not None:
        try:
            store = RedisQueueStore(redis_url=redis_url, prefix=redis_prefix)
            await store.initialize()
            logger.info("Kuyruk arka planı Redis olarak başlatıldı")
            return store
        except Exception as exc:
            if backend == "redis":
                raise
            logger.warning(f"Redis kullanılamadı, dosya kuyruğuna düşülüyor: {exc}")

    store = FileQueueStore(state_file=state_file)
    await store.initialize()
    logger.info("Kuyruk arka planı dosya tabanlı olarak başlatıldı")
    return store

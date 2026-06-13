from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Optional

try:
    from google.cloud import storage
except Exception:  # pragma: no cover - optional dependency
    storage = None

logger = logging.getLogger(__name__)


class GCSArtifactStore:
    backend_name = "gcs"

    def __init__(self, bucket_name: str, prefix: str):
        if storage is None:
            raise RuntimeError("google-cloud-storage package is not installed")

        self.client = storage.Client()
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")
        self.bucket = self.client.bucket(bucket_name)

    async def initialize(self) -> None:
        # Bucket varlığı ilk yazmada GCS tarafından doğrulanır. Burada
        # bucket.exists() çağırmak, yalnız nesne yazma yetkisi olan çalışma
        # hesabına gereksiz storage.buckets.get izni verilmesini gerektirir.
        return None

    async def close(self) -> None:
        return None

    def object_name(self, *parts: str) -> str:
        clean_parts = [part.strip("/") for part in parts if part]
        return "/".join([self.prefix, *clean_parts]) if self.prefix else "/".join(clean_parts)

    def blob_url(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name}"

    async def upload_json(self, object_name: str, payload: dict) -> str:
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        return self.blob_url(object_name)

    async def upload_pdf(self, object_name: str, pdf_bytes: bytes) -> str:
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(pdf_bytes, content_type="application/pdf")
        return self.blob_url(object_name)

    async def upload_text(self, object_name: str, text: str) -> str:
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(text, content_type="text/plain; charset=utf-8")
        return self.blob_url(object_name)


async def build_artifact_store(bucket_name: str, prefix: str) -> Optional[GCSArtifactStore]:
    if not bucket_name or storage is None:
        return None

    try:
        store = GCSArtifactStore(bucket_name=bucket_name, prefix=prefix)
        await store.initialize()
        logger.info("Cloud artifact store GCS olarak başlatıldı")
        return store
    except Exception as exc:
        logger.warning(f"GCS artifact store kullanılamadı: {exc}")
        return None

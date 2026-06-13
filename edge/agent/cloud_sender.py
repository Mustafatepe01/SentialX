import json
import logging
from pathlib import Path

import google.auth
from google.api_core.exceptions import PreconditionFailed
from google.auth import impersonated_credentials
from google.cloud import pubsub_v1, storage

from outbox import delete_event


logger = logging.getLogger(__name__)


class CloudSender:
    def __init__(self, settings: dict):
        self.settings = settings
        self.storage_client = None
        self.publisher_client = None
        self.topic_path = None

    def connect(self) -> None:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        credentials, detected_project = google.auth.default(scopes=scopes)
        service_account = self.settings.get("edge_service_account", "").strip()
        if service_account:
            credentials = impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=service_account,
                target_scopes=scopes,
                lifetime=3600,
            )
        project_id = self.settings.get("project_id") or detected_project
        self.storage_client = storage.Client(
            project=project_id,
            credentials=credentials,
        )
        self.publisher_client = pubsub_v1.PublisherClient(
            credentials=credentials
        )
        self.topic_path = self.publisher_client.topic_path(
            project_id,
            self.settings["pubsub_topic"],
        )
        logger.info("Google Cloud istemcileri hazir")

    def send(self, package_path: Path) -> None:
        if self.storage_client is None:
            self.connect()

        event_path = package_path / "event.json"
        event = json.loads(event_path.read_text(encoding="utf-8"))
        prefix = (
            f"{event['customer_id']}/frames/{event['camera_id']}/"
            f"{event['captured_at'][:10]}/{event['event_id']}"
        )
        bucket = self.storage_client.bucket(self.settings["bucket"])

        if not event.get("gcs_uploaded"):
            for frame_name in event["frames"]:
                blob = bucket.blob(f"{prefix}/{frame_name}")
                try:
                    blob.upload_from_filename(
                        str(package_path / frame_name),
                        content_type="image/jpeg",
                        if_generation_match=0,
                    )
                except PreconditionFailed:
                    pass

            cloud_event = {
                key: value
                for key, value in event.items()
                if key not in {"gcs_uploaded", "published"}
            }
            cloud_event["gcs_uri"] = f"gs://{self.settings['bucket']}/{prefix}"
            try:
                bucket.blob(f"{prefix}/meta.json").upload_from_string(
                    json.dumps(cloud_event, ensure_ascii=False, indent=2),
                    content_type="application/json",
                    if_generation_match=0,
                )
            except PreconditionFailed:
                pass
            event["gcs_uploaded"] = True
            event["gcs_uri"] = cloud_event["gcs_uri"]
            event_path.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if not event.get("published"):
            message = {
                key: value
                for key, value in event.items()
                if key not in {"gcs_uploaded", "published", "frames"}
            }
            future = self.publisher_client.publish(
                self.topic_path,
                json.dumps(message, ensure_ascii=False).encode("utf-8"),
                event_id=event["event_id"],
                customer_id=event["customer_id"],
                camera_id=event["camera_id"],
                schema_version=str(event["schema_version"]),
            )
            event["pubsub_message_id"] = future.result(timeout=30)
            event["published"] = True
            event_path.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        try:
            delete_event(package_path)
        except OSError as exc:
            logger.warning(
                "[%s] Cloud gonderimi tamamlandi; yerel klasor temizligi bekliyor: %s",
                event["event_id"],
                exc,
            )
            return
        logger.info("[%s] Cloud gonderimi tamamlandi", event["event_id"])

    def reset(self) -> None:
        self.storage_client = None
        self.publisher_client = None
        self.topic_path = None

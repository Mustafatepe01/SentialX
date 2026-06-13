import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "edge" / "agent" / "config.py"
SPEC = importlib.util.spec_from_file_location("sentialx_edge_config", CONFIG_PATH)
edge_config = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None

google_module = types.ModuleType("google")
google_auth_module = types.ModuleType("google.auth")
impersonated_module = types.ModuleType("google.auth.impersonated_credentials")
transport_module = types.ModuleType("google.auth.transport")
requests_module = types.ModuleType("google.auth.transport.requests")
requests_module.AuthorizedSession = object
google_module.auth = google_auth_module
google_auth_module.impersonated_credentials = impersonated_module
google_auth_module.transport = transport_module
transport_module.requests = requests_module

with patch.dict(
    sys.modules,
    {
        "google": google_module,
        "google.auth": google_auth_module,
        "google.auth.impersonated_credentials": impersonated_module,
        "google.auth.transport": transport_module,
        "google.auth.transport.requests": requests_module,
    },
):
    SPEC.loader.exec_module(edge_config)


class EdgeCameraConfigTests(unittest.TestCase):
    def test_normalize_camera_builds_encoded_rtsp_url_and_routes_models(self):
        camera_data = {
            "cameras": [
                {
                    "camera_id": "11111111-1111-4111-8111-111111111111",
                    "camera_name": "Combined Camera",
                    "area_name": "warehouse",
                    "rtsp_host": "127.0.0.1",
                    "rtsp_port": 8554,
                    "rtsp_path": "camera3",
                    "rtsp_username": "edge user",
                    "credential_key": "mediamtx-default",
                    "processing_mode": "motion",
                    "analysis_types": ["ppe", "fire"],
                    "top_frames": 3,
                }
            ]
        }
        secrets = {
            "credentials": {
                "mediamtx-default": {
                    "username": "ignored",
                    "password": "p@ss word",
                }
            }
        }

        cameras = edge_config.normalize_cameras(camera_data, secrets)

        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["analysis_types"], ["ppe", "fire"])
        self.assertEqual(cameras[0]["top_frames"], 3)
        self.assertEqual(
            cameras[0]["url"],
            "rtsp://edge%20user:p%40ss%20word@127.0.0.1:8554/camera3",
        )

    def test_normalize_camera_rejects_missing_local_credential(self):
        camera_data = {
            "cameras": [
                {
                    "camera_id": "11111111-1111-4111-8111-111111111111",
                    "credential_key": "missing",
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "Eksik yerel credential"):
            edge_config.normalize_cameras(camera_data, {"credentials": {}})


if __name__ == "__main__":
    unittest.main()

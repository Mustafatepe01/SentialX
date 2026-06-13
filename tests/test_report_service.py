import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


os.environ["MOCK_MODE"] = "1"
os.environ["QUEUE_BACKEND"] = "file"
REPORT_SERVICE_DIR = (
    Path(__file__).resolve().parents[1]
    / "cloud_two_service"
    / "report-service"
)
sys.path.insert(0, str(REPORT_SERVICE_DIR))

from models import ViolationGroup  # noqa: E402
from report import count_critical_violations  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main as report_main  # noqa: E402


class ReportAggregationTests(unittest.TestCase):
    def test_critical_count_includes_every_fire_detection(self):
        groups = [
            ViolationGroup(
                bolge="Depo",
                ihlal_tipi="yangin",
                ihlal_alt_tipi="acik_alev",
                adet=3,
                zamanlar=["10:00", "10:01", "10:02"],
                frame_urls=[],
                aciklamalar=[],
            ),
            ViolationGroup(
                bolge="Hat-1",
                ihlal_tipi="ppe_ihlali",
                ihlal_alt_tipi="baretsiz",
                adet=2,
                zamanlar=["10:03", "10:04"],
                frame_urls=[],
                aciklamalar=[],
            ),
        ]

        self.assertEqual(count_critical_violations(groups), 3)

    def test_report_endpoint_returns_mock_report(self):
        now = datetime.now()
        payload = {
            "tesis_id": "T-1001",
            "tesis_adi": "Demo Fabrika",
            "tesis_adresi": "Istanbul",
            "vardiya": "2",
            "vardiya_baslangic": (now - timedelta(hours=1)).isoformat(),
            "vardiya_bitis": now.isoformat(),
            "sorumlu_isg_uzmani": "Test Uzmani",
            "violations": [
                {
                    "id": "v1",
                    "tesis_id": "T-1001",
                    "kamera_id": "cam-01",
                    "ihlal_tipi": "yangin",
                    "ihlal_alt_tipi": "acik_alev",
                    "bolge": "Depo",
                    "guven_skoru": 0.95,
                    "tespit_zamani": now.isoformat(),
                    "vardiya": "2",
                }
            ],
        }

        with TestClient(report_main.app) as client:
            response = client.post("/report", json=payload)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["toplam_ihlal"], 1)
        self.assertEqual(body["kritik_ihlal"], 1)
        self.assertIn("mock modda", body["rapor_metni"])


if __name__ == "__main__":
    unittest.main()

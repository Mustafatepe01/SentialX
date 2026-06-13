import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRAME_WORKER_PATH = ROOT / "cloud" / "frame-worker" / "main.py"


class FrameWorkerContractTests(unittest.TestCase):
    def test_fire_alert_precedes_vlm_and_report_calls(self):
        tree = ast.parse(FRAME_WORKER_PATH.read_text(encoding="utf-8"))
        process_function = next(
            node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "process_pubsub"
        )
        call_lines = {}
        for node in ast.walk(process_function):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                call_lines.setdefault(node.func.id, []).append(node.lineno)

        alert_line = min(call_lines["ensure_fire_alert_published"])
        vlm_line = min(call_lines["run_vlm_analysis"])
        report_line = min(call_lines["create_report"])

        self.assertLess(alert_line, vlm_line)
        self.assertLess(alert_line, report_line)


if __name__ == "__main__":
    unittest.main()

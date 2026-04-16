from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


class ImportSmokeTests(unittest.TestCase):
    def test_runtime_module_exports(self) -> None:
        runtime = importlib.import_module("hockey_app.runtime.app")
        self.assertTrue(hasattr(runtime, "launch_predictions_ui"))
        self.assertTrue(hasattr(runtime, "download_missing_simulations"))
        self.assertTrue(hasattr(runtime, "compile_probability_tables"))

    def test_entrypoint_import_resolves_runtime(self) -> None:
        app = importlib.import_module("hockey_app.app")
        mod = app._import_runtime_app()
        self.assertEqual(mod.__name__, "hockey_app.runtime.app")

    def test_web_export_payload_from_simulation_csv(self) -> None:
        exporter = importlib.import_module("hockey_app.tools.export_web")
        with tempfile.TemporaryDirectory() as tmp:
            sims_dir = Path(tmp)
            (sims_dir / "simulations_2026_04_08.csv").write_text(
                "\n".join(
                    [
                        "scenerio,teamCode,madePlayoffs,round2,round3,round4,wonCup",
                        "ALL,BOS,0.9,0.7,0.4,0.2,0.1",
                        "ALL,NYR,0.8,0.6,0.3,0.1,0.05",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            payload = exporter.build_payload(
                season="2025-2026",
                start=exporter.dt.date(2026, 4, 8),
                end=exporter.dt.date(2026, 4, 8),
                simulations_dir=sims_dir,
            )

        self.assertEqual(payload["metadata"]["season"], "2025-2026")
        self.assertIn("madeplayoffs", payload["tables"])
        self.assertEqual(payload["tables"]["madeplayoffs"]["rows"]["BOS"], [0.9])
        self.assertEqual(payload["teams"][0]["code"], "BOS")


if __name__ == "__main__":
    unittest.main()

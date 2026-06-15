import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from scripts import update_duty_pharmacies as updater


def source_html(date: str, pharmacy_count: int = updater.MIN_PHARMACIES) -> str:
    cards = []
    for index in range(pharmacy_count):
        cards.append(
            f"""
            <div class="pharmacy-card">
              <h3>Pharmacie {index}</h3>
              <span class="truncate">Niamey</span>
              <span class="line-clamp-2">Quartier {index}, Niamey</span>
              <a href="tel:9000000{index}">Appeler</a>
              <a href="https://google.com/maps/dir/?destination=13.5,2.1">Carte</a>
            </div>
            """
        )
    return f"<html><title>Gardes du {date}</title><body>{''.join(cards)}</body></html>"


class UpdateDutyPharmaciesTest(unittest.TestCase):
    def test_build_payload_accepts_valid_source_for_today(self):
        with patch.object(
            updater, "niamey_now", return_value=datetime(2026, 6, 15, 12, 0)
        ):
            payload = updater.build_payload(source_html("15/06/2026"))

        self.assertEqual(payload["date"], "2026-06-15")
        self.assertEqual(len(payload["data"]), updater.MIN_PHARMACIES)

    def test_main_keeps_valid_publication_when_source_is_stale(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "pharmacies_garde_current.json"
            output_path.write_text(
                json.dumps(
                    {
                        "status": "success",
                        "city": updater.CITY,
                        "data": [{}] * updater.MIN_PHARMACIES,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(updater, "OUTPUT_PATH", output_path),
                patch.object(updater, "download_source", return_value="<html></html>"),
            ):
                self.assertEqual(updater.main(), 0)

    def test_main_fails_when_source_and_existing_publication_are_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "pharmacies_garde_current.json"
            with (
                patch.object(updater, "OUTPUT_PATH", output_path),
                patch.object(updater, "download_source", return_value="<html></html>"),
            ):
                with self.assertRaises(updater.SourceUnavailableError):
                    updater.main()


if __name__ == "__main__":
    unittest.main()

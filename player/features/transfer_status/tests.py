from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from player.features.transfer_status.status import status_text


class TransferStatusTests(SimpleTestCase):
    def test_message(self):
        self.assertEqual(
            status_text(
                {
                    "status": "transferred",
                    "resumed": True,
                    "message": "Transferred and resumed.",
                }
            ),
            "Transferred and resumed.",
        )

    def test_error(self):
        self.assertEqual(
            status_text(
                {
                    "error": "Device not found or not available",
                    "code": "device_unreachable",
                }
            ),
            "Device not found or not available",
        )
        # A success-shaped body that also carries an error stays an error.
        self.assertEqual(
            status_text(
                {
                    "status": "transferred",
                    "message": "Transferred and resumed.",
                    "error": "Transferred but could not resume playback: timeout",
                    "code": "transfer_failed",
                }
            ),
            "Transferred but could not resume playback: timeout",
        )

    def test_empty_body(self):
        self.assertEqual(status_text({}), "")
        self.assertEqual(status_text(None), "")


class TransferStatusPageTests(SimpleTestCase):
    def test_handlers_write_message_or_error_into_player_status(self):
        template = Path(settings.BASE_DIR, "player/templates/player/index.html").read_text()
        helper = template.split("function applyTransferStatus", 1)[1].split("function selectWebPlayer", 1)[0]
        web = template.split("function selectWebPlayer()", 1)[1].split("function selectDevice(", 1)[0]
        device = template.split("function selectDevice(", 1)[1].split("let allPlaylists", 1)[0]

        self.assertLess(helper.index("data.error"), helper.index("data.message"))
        self.assertIn("playerStatus.textContent = data.error", helper)
        self.assertIn("playerStatus.textContent = data.message", helper)

        self.assertIn("/select-web-player/", web)
        self.assertIn("/transfer/", device)
        for block, marker in ((web, "selected"), (device, "transferred")):
            self.assertLess(block.index("applyTransferStatus(data)"), block.index(f"data.status === '{marker}'"))
            self.assertLess(block.index("data.error"), block.index(f"data.status === '{marker}'"))

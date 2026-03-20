import unittest

from app.connectors.drive import DriveConnector, DriveFile


class _StubDriveConnector(DriveConnector):
    def __init__(self):
        super().__init__(local_inbox="data/inbox", local_output="data/output")
        self._status = {}
        self._files = []

    def load_status(self) -> dict:
        return self._status

    def list_inbox(self) -> list[DriveFile]:
        return self._files

    def download(self, drive_file: DriveFile):
        return f"/tmp/{drive_file.name}"


class DriveConnectorTest(unittest.TestCase):
    def test_get_next_untranslated_only_accepts_docx(self):
        connector = _StubDriveConnector()
        connector._files = [
            DriveFile(id="1", name="legacy.doc"),
            DriveFile(id="2", name="ok.docx"),
        ]

        result = connector.get_next_untranslated()

        self.assertIsNotNone(result)
        drive_file, local_path = result
        self.assertEqual(drive_file.name, "ok.docx")
        self.assertTrue(local_path.endswith("ok.docx"))


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path

from app.core.config import Config


class ConfigTest(unittest.TestCase):
    def test_from_yaml_accepts_data_dir(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            configured_data_dir = tmp_path / "custom_data"
            config_file = tmp_path / "config.yaml"
            config_file.write_text(f"data_dir: {configured_data_dir}\ntranslator: mock\n")

            cfg = Config.from_yaml(str(config_file))

            self.assertEqual(cfg.data_dir, configured_data_dir)
            self.assertEqual(cfg.translator, "mock")
            self.assertEqual(cfg.tm_dir, configured_data_dir / "tm")


if __name__ == "__main__":
    unittest.main()

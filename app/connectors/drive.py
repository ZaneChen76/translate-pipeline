from __future__ import annotations
"""Google Drive connector — fetch source docs and push translated output."""

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..core.config import log

# Drive folder IDs (from translate/ structure)
TRANSLATE_ROOT = os.environ.get("GDRIVE_TRANSLATE_ROOT", "1AP204wgRBcOJldQaJE9Syaj2X1cH_WjQ")
IN_FOLDER_ID = os.environ.get("GDRIVE_IN_FOLDER", "1aXjL-HvfOkrSn7ABcK-0M62ifZA2Ap3r")
OUT_FOLDER_ID = os.environ.get("GDRIVE_OUT_FOLDER", "1VKAot0kBw7jTWQbUWvKSBSrBqnfkLUtL")

GOG_BIN = os.environ.get("GOG_BIN", "gog")
STATUS_FILE = "status.json"


def _run_gog(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """Run a gog CLI command and return (returncode, stdout, stderr)."""
    cmd = [GOG_BIN, "drive"] + args
    log.debug(f"gog drive: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _parse_tsv_lines(output: str) -> list[dict[str, str]]:
    """Parse gog --plain output into list of dicts (lowercase keys).
    
    Handles both table format (tab-separated columns) and vertical format (key\\tvalue per line).
    """
    lines = [l.strip() for l in output.strip().split("\n") if l.strip()]
    if not lines:
        return []
    
    first_line_parts = lines[0].split("\t")
    if len(first_line_parts) == 2 and len(lines) > 1:
        is_vertical = all("\t" in l and len(l.split("\t")) == 2 for l in lines)
        if is_vertical:
            row = {parts[0].lower(): parts[1] for l in lines if (parts := l.split("\t", 1))}
            return [row]
    
    headers = [h.lower() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        vals = line.split("\t")
        row = {}
        for i, h in enumerate(headers):
            row[h] = vals[i] if i < len(vals) else ""
        rows.append(row)
    return rows


@dataclass
class DriveFile:
    id: str
    name: str
    size: Optional[int] = None
    mime_type: str = ""
    link: str = ""


class DriveConnector:
    """Google Drive connector for translate/in and translate/out folders."""

    def __init__(
        self,
        in_folder_id: str = IN_FOLDER_ID,
        out_folder_id: str = OUT_FOLDER_ID,
        local_inbox: str = "data/inbox",
        local_output: str = "data/output",
    ):
        self.in_folder_id = in_folder_id
        self.out_folder_id = out_folder_id
        self.local_inbox = Path(local_inbox)
        self.local_output = Path(local_output)
        self.local_inbox.mkdir(parents=True, exist_ok=True)
        self.local_output.mkdir(parents=True, exist_ok=True)

    # ── Status management (single status.json in in/) ──

    def load_status(self) -> dict:
        """Load the unified status.json from Drive in/ folder.
        
        Returns dict of {filename: status_record}.
        """
        # Find status.json in Drive in/
        rc, stdout, stderr = _run_gog(
            ["ls", "--parent", self.in_folder_id, "--plain"]
        )
        if rc != 0:
            return {}
        
        rows = _parse_tsv_lines(stdout)
        status_file_id = None
        for row in rows:
            if row.get("name") == STATUS_FILE:
                status_file_id = row.get("id")
                break
        
        if not status_file_id:
            return {}
        
        # Download to temp and read
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp_path = f.name
        
        try:
            rc, _, _ = _run_gog(["download", status_file_id, "--out", tmp_path])
            if rc != 0:
                return {}
            with open(tmp_path) as f:
                return json.load(f)
        except Exception:
            return {}
        finally:
            os.unlink(tmp_path)

    def save_status(self, status: dict) -> bool:
        """Save the unified status.json to Drive in/ folder.
        
        Args:
            status: dict of {filename: status_record}
        """
        # Find existing status.json file ID
        rc, stdout, stderr = _run_gog(
            ["ls", "--parent", self.in_folder_id, "--plain"]
        )
        existing_id = None
        if rc == 0:
            for row in _parse_tsv_lines(stdout):
                if row.get("name") == STATUS_FILE:
                    existing_id = row.get("id")
                    break
        
        # Write to local file
        local_path = self.local_inbox / STATUS_FILE
        with open(local_path, "w") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        
        if existing_id:
            # Delete old version first (gog doesn't have update-in-place)
            _run_gog(["delete", existing_id, "--force"])
        
        # Upload new version
        rc, stdout, stderr = _run_gog(
            ["upload", str(local_path), "--parent", self.in_folder_id, "--plain"],
            timeout=60,
        )
        if rc != 0:
            log.error(f"Failed to upload status.json: {stderr}")
            return False
        
        log.info(f"Status.json updated ({len(status)} entries)")
        return True

    def mark_processed(self, filename: str, record: dict) -> bool:
        """Mark a file as processed in the status.json."""
        status = self.load_status()
        status[filename] = record
        return self.save_status(status)

    def is_processed(self, filename: str) -> bool:
        """Check if a file has already been processed."""
        status = self.load_status()
        entry = status.get(filename, {})
        return entry.get("status") == "success"

    # ── Drive operations ──

    def list_inbox(self) -> list[DriveFile]:
        """List files in the Drive translate/in folder (excluding status.json)."""
        rc, stdout, stderr = _run_gog(
            ["ls", "--parent", self.in_folder_id, "--plain"]
        )
        if rc != 0:
            log.error(f"Drive list_inbox failed: {stderr}")
            return []

        rows = _parse_tsv_lines(stdout)
        files = []
        for row in rows:
            name = row.get("name", "")
            if name == STATUS_FILE:
                continue
            files.append(DriveFile(
                id=row.get("id", ""),
                name=name,
                size=int(float(row["size"].split()[0])) if row.get("size") and row["size"] != "-" else None,
                mime_type=row.get("type", ""),
            ))
        log.info(f"Drive inbox: {len(files)} files")
        return files

    def download(self, drive_file: DriveFile) -> Optional[str]:
        """Download a file from Drive to local inbox. Returns local path."""
        dest = self.local_inbox / drive_file.name
        rc, stdout, stderr = _run_gog(
            ["download", drive_file.id, "--out", str(dest)],
            timeout=300,
        )
        if rc != 0:
            log.error(f"Drive download failed: {stderr}")
            return None
        log.info(f"Downloaded: {drive_file.name} → {dest}")
        return str(dest)

    def upload_to_out(self, local_path: str, name: str = "") -> Optional[DriveFile]:
        """Upload a file to the Drive translate/out folder."""
        path = Path(local_path)
        if not name:
            name = path.name

        rc, stdout, stderr = _run_gog(
            ["upload", str(path), "--parent", self.out_folder_id, "--plain"],
            timeout=600,
        )
        if rc != 0:
            log.error(f"Drive upload failed: {stderr}")
            return None

        rows = _parse_tsv_lines(stdout)
        file_id = rows[0].get("id", "") if rows else ""
        link = rows[0].get("link", "") if rows else ""
        log.info(f"Uploaded to Drive out: {name}")
        return DriveFile(id=file_id, name=name, link=link)

    def get_next_untranslated(self) -> Optional[tuple[DriveFile, str]]:
        """Get the next untranslated file from Drive inbox.
        
        Skips files that have status='success' in the in/ status.json.
        Returns (DriveFile, local_path) or None if no untranslated files.
        """
        status = self.load_status()
        files = self.list_inbox()
        
        for f in files:
            if not f.name.lower().endswith((".docx", ".doc")):
                log.info(f"Skipping non-DOCX: {f.name}")
                continue
            
            entry = status.get(f.name, {})
            if entry.get("status") == "success":
                log.info(f"Already translated: {f.name}")
                continue
            
            local_path = self.download(f)
            if local_path:
                return f, local_path
        return None

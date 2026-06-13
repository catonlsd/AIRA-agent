# File: backend/app/artifacts/delivery.py
"""
Artifact delivery — where the file is saved and how the user reaches it.

Default: a safe workspace output folder (settings.artifacts_dir), exposed via a
clean download path. If the user asks to save to an explicit location OUTSIDE
that safe area, delivery flags it as requiring approval — the product never
writes to arbitrary user paths silently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings

# "save to/in/at <path>" with a real path (drive letter, slash, or ~).
_SAVE_PATH = re.compile(
    r"\bsave\s+(?:it\s+|this\s+|the\s+\w+\s+)?(?:to|in|at|under|into)\s+"
    r"([A-Za-z]:[\\/][^\s\"']+|~?/[^\s\"']+|\.{1,2}/[^\s\"']+)",
    re.IGNORECASE,
)


@dataclass
class DeliveryTarget:
    filename: str
    path: Path                 # absolute path the file is actually written to
    location: str              # "workspace" | "external"
    requires_approval: bool
    requested_path: Optional[str] = None  # the user's external request, if any
    download_url: Optional[str] = None


class ArtifactDeliveryService:
    def _root(self) -> Path:
        root = Path(settings.artifacts_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def detect_requested_path(self, goal: str) -> Optional[str]:
        match = _SAVE_PATH.search(goal or "")
        return match.group(1) if match else None

    def resolve(self, goal: str, filename: str) -> DeliveryTarget:
        """Resolve where to write. External requests are flagged for approval.

        For safety the file is always written inside the workspace artifacts
        area (the file tools are sandboxed); an external request is recorded and
        surfaced so the user can move/download it deliberately.
        """
        root = self._root()
        path = root / filename
        requested = self.detect_requested_path(goal)
        if requested is None:
            return DeliveryTarget(
                filename=filename,
                path=path,
                location="workspace",
                requires_approval=False,
                download_url=f"/artifacts/{filename}",
            )

        # An explicit external location was requested.
        requested_abs = Path(requested).expanduser()
        outside = root not in requested_abs.resolve().parents
        return DeliveryTarget(
            filename=filename,
            path=path,  # still the safe workspace path
            location="external",
            requires_approval=bool(outside),
            requested_path=requested,
            download_url=f"/artifacts/{filename}",
        )

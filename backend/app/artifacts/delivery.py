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
    owner_token: str = ""      # the owner directory this artifact lives under
    requested_path: Optional[str] = None  # the user's external request, if any
    download_url: Optional[str] = None


class ArtifactDeliveryService:
    def _owner_dir(self, owner_token: str) -> Path:
        # Each owner gets an isolated subdirectory so cross-owner filename
        # guessing can't reach another user's files; the token is an HMAC.
        token = (owner_token or "shared").replace("/", "").replace("\\", "").replace("..", "")
        root = (Path(settings.artifacts_dir).resolve() / token)
        root.mkdir(parents=True, exist_ok=True)
        return root

    def detect_requested_path(self, goal: str) -> Optional[str]:
        match = _SAVE_PATH.search(goal or "")
        return match.group(1) if match else None

    def resolve(self, goal: str, filename: str, owner_token: str = "shared") -> DeliveryTarget:
        """Resolve where to write, scoped to the owner. External requests are
        flagged for approval.

        The file is always written inside the owner's workspace artifacts area
        (file tools are sandboxed); the download URL is owner-scoped so access is
        enforced at the route, not by an unguessable filename alone.
        """
        owner_dir = self._owner_dir(owner_token)
        path = owner_dir / filename
        download_url = f"/artifacts/{owner_token}/{filename}"
        requested = self.detect_requested_path(goal)
        if requested is None:
            return DeliveryTarget(
                filename=filename,
                path=path,
                location="workspace",
                requires_approval=False,
                owner_token=owner_token,
                download_url=download_url,
            )

        requested_abs = Path(requested).expanduser()
        outside = owner_dir not in requested_abs.resolve().parents
        return DeliveryTarget(
            filename=filename,
            path=path,  # still the safe, owner-scoped workspace path
            location="external",
            requires_approval=bool(outside),
            owner_token=owner_token,
            requested_path=requested,
            download_url=download_url,
        )

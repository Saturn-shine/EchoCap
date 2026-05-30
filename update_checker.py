"""
Check GitHub Releases for newer versions (background thread, non-blocking).
"""

import json
import logging
import threading
import urllib.request

from paths import VERSION_PATH

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com/repos/saturnshine/EchoCap/releases/latest"


def _read_local_version():
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "1.0.0"


def check_for_updates(on_result=None):
    """Check GitHub for newer releases in a background thread.

    Args:
        on_result: Optional callback(latest_version) called on main thread
                   if a newer version is found. Called with None if up to date
                   or if the check fails.
    """

    def _check():
        local = _read_local_version()
        try:
            req = urllib.request.Request(GITHUB_API)
            req.add_header("Accept", "application/vnd.github+json")
            req.add_header("User-Agent", "EchoCap")
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode())
            remote = data.get("tag_name", "").lstrip("v")

            if remote and remote != local:
                logger.info("Update available: %s -> %s", local, remote)
                if on_result:
                    on_result(remote)
                return

            logger.debug("Up to date (%s).", local)
        except Exception as e:
            logger.debug("Update check failed: %s", e)

    t = threading.Thread(target=_check, daemon=True)
    t.start()

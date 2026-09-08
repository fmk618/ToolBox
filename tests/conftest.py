"""Shared pytest setup.

Env vars are read by ``toolbox.core.limits`` at import time, so they must be
set here — before any test module imports ``toolbox``.
"""

import os

# Small bucket so the 429 test only needs a few requests.
os.environ["TOOLBOX_RATE_LIMIT"] = "3/minute"
# Small cap (1 MB) so the 413 test only needs a 2 MB body.
os.environ["TOOLBOX_MAX_UPLOAD_MB"] = "1"
os.environ["TOOLBOX_DEBUG"] = "0"

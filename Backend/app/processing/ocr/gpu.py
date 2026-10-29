"""One lock for the integrated GPU.

The learned restorer and PP-OCR's text detector each hold a DirectML session. Running two sessions on the device at
the same moment from different threads (candidate readings and pages are read in parallel) can crash the process in
the driver, with no Python error. Every DirectML run takes this lock; CPU sessions do not need it.
"""

from __future__ import annotations

import threading

GPU_LOCK = threading.Lock()

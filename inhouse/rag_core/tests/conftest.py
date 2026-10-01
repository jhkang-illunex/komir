"""Document-backend fixtures are opt-in to the test process only."""

import os
from pathlib import Path


_ROOT = Path(__file__).parent / "fixtures" / "document_backend"
os.environ.setdefault("PAGEINDEX_TREES_DIR", str(_ROOT / "trees"))
os.environ.setdefault("OKF_DOCUMENTS_DIR", str(_ROOT / "okf"))

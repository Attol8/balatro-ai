"""Keep the copied state factory local to this focused test directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

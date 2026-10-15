import sys
from pathlib import Path

# Rende importabile tests/fakes.py dai moduli di test.
sys.path.insert(0, str(Path(__file__).parent))

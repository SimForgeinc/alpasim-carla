import sys
from pathlib import Path

# Allow running the suite from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

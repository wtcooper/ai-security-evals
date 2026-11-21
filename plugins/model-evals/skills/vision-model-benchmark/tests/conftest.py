import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
for p in (SKILL, SKILL / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

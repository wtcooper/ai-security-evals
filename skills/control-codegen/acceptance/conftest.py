# Registers the shared probe plugin (options --base-url/--findings-out/--acceptance-out/--ctx,
# fixtures api/two_users, mark/assert_secure). Suites live in <spec>/ subdirs.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "probes"))  # spec helpers
from probelib import *  # noqa: F401,F403,E402

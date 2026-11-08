from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.slow
def test_full_training_league():
    subprocess.run([sys.executable, "tools/league.py", "--full", "--label", "pytest-full"],
                   cwd=ROOT, check=True, timeout=14_400)


@pytest.mark.slow
def test_explicit_milestone_holdout_league():
    subprocess.run([sys.executable, "tools/league.py", "--full", "--group", "holdout",
                    "--milestone", "pytest-holdout", "--label", "pytest-holdout"],
                   cwd=ROOT, check=True, timeout=7200)

import sys
from pathlib import Path

import cv2
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture
def shot():
    def load(name: str):
        img = cv2.imread(str(FIXTURES / name))
        assert img is not None, f"print não encontrado: {name}"
        return img
    return load

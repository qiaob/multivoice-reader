"""The Kotlin port in android/core is tested against what this code does (android/tools/make_golden.py).
If this fails, the Python side changed: run that script again, then the Kotlin tests."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "android" / "core" / "src" / "test" / "resources" / "golden"


def test_the_kotlin_ports_expected_results_are_up_to_date(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "make_golden", ROOT / "android" / "tools" / "make_golden.py"
    )
    make_golden = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_golden)
    make_golden.main(tmp_path)
    for path in sorted(GOLDEN.glob("*.json")):
        assert (tmp_path / path.name).read_bytes() == path.read_bytes(), f"{path.name} 过期了"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(p.name for p in GOLDEN.glob("*.json"))

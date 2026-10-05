"""Fallback test runner when pytest is not installed:  python run_tests_plain.py"""
import importlib, inspect, sys, tempfile, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent)); sys.path.insert(0, str(Path(__file__).parent / "tests"))
failed = passed = 0
for path in sorted((Path(__file__).parent / "tests").glob("test_*.py")):
    mod = importlib.import_module(path.stem)
    for name, fn in inspect.getmembers(mod, inspect.isfunction):
        if not name.startswith("test_"):
            continue
        params = inspect.signature(fn).parameters
        try:
            if "tmp_path" in params:
                fn(Path(tempfile.mkdtemp()))
            else:
                fn()
            passed += 1
        except Exception:
            failed += 1; print("FAIL", path.stem, name); traceback.print_exc()
print(f"{passed} passed, {failed} failed"); sys.exit(1 if failed else 0)

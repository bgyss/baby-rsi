import importlib
import json
import os

MODULE = 'policy'
FUNC = 'decide'
VISIBLE = [['personal data', 1]]

def load_hidden():
    path = os.environ.get("SIRO_HIDDEN_PATH")
    if not path:
        return []
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("cases", [])

def call(fn, row):
    if isinstance(row, list):
        *args, expected = row
    else:
        args, expected = row[:-1], row[-1]
    return fn(*args), expected

def main():
    mod = importlib.import_module(MODULE)
    fn = getattr(mod, FUNC)
    rows = VISIBLE + load_hidden()
    passed = 0
    errors = 0
    for row in rows:
        try:
            got, expected = call(fn, row)
        except Exception:
            errors += 1
            continue
        if got == expected:
            passed += 1
    total = len(rows)
    acc = passed / total if total else 0.0
    print(json.dumps({"primary": acc, "passed": passed == total, "secondary": {"cases": total, "failed": total - passed, "errors": errors}, "notes": f"{passed}/{total} cases"}))

if __name__ == "__main__":
    main()

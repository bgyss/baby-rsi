import importlib
import json
import os


def main():
    cfg = importlib.import_module("config").CONFIG
    with open(os.environ["SIRO_HIDDEN_PATH"], "r", encoding="utf-8") as fh:
        target = json.load(fh)["target"]
    lr = float(cfg.get("learning_rate", 0.0))
    steps = int(cfg.get("steps", 0))
    loss = abs(lr - float(target["learning_rate"])) + abs(steps - int(target["steps"])) / 100.0
    passed = loss <= 0.05
    print(json.dumps({"primary": loss, "passed": passed, "secondary": {"steps": steps}, "notes": f"loss={loss:.4f}"}))

if __name__ == "__main__":
    main()

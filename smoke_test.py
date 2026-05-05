"""Smoke test: exercise routes via Flask test client in DRY_RUN mode."""
import os
import sys

os.environ["DRY_RUN"] = "1"
os.environ.setdefault("PRINTER_HOST", "127.0.0.1")
os.environ.setdefault("PRINTER_PORT", "9100")

from app.main import create_app  # noqa: E402

SAMPLE = """# Buy groceries

- [ ] milk
- [ ] **6** eggs
- [x] bread

;;;

# Call dentist

> reschedule for next week

;;;

# Wi-Fi for guests

```qr
WIFI:T:WPA;S:HomeNet;P:hunter2;;
```
"""


def main() -> int:
    app = create_app()
    client = app.test_client()

    failures = []

    r = client.get("/healthz")
    if r.status_code != 200 or not r.get_json().get("ok"):
        failures.append(f"healthz failed: {r.status_code} {r.get_data(as_text=True)}")

    r = client.post("/render", data={"text": SAMPLE})
    if r.status_code != 200:
        failures.append(f"render status {r.status_code}: {r.get_data(as_text=True)[:200]}")
    body = r.get_data(as_text=True)
    for needle in ("strip", "Buy groceries", "Call dentist", "qr", "[ ]", "[x]"):
        if needle.lower() not in body.lower():
            failures.append(f"render missing {needle!r}")

    r = client.post("/render", data={"text": ""})
    if r.status_code != 200:
        failures.append(f"empty render status {r.status_code}")

    r = client.post("/print", data={"text": SAMPLE})
    if r.status_code != 200 or not r.get_json().get("ok"):
        failures.append(f"print failed: {r.status_code} {r.get_data(as_text=True)}")
    elif r.get_json().get("printed") != 3:
        failures.append(f"expected 3 strips, got {r.get_json()}")

    r = client.post("/test")
    if r.status_code != 200 or not r.get_json().get("ok"):
        failures.append(f"test print failed: {r.status_code} {r.get_data(as_text=True)}")

    r = client.get("/")
    if r.status_code != 200:
        failures.append(f"index status {r.status_code}")
    elif "editor" not in r.get_data(as_text=True):
        failures.append("index missing editor element")

    if failures:
        print("FAIL")
        for f in failures:
            print(f" - {f}")
        return 1
    print("OK: all smoke tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

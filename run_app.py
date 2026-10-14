"""Start OpenHand 112: API + dashboard on http://localhost:8001

    python run_app.py                 # demo clock runs 10x real time
    DEMO_SPEED=1 python run_app.py    # real time
    PORT=8002 python run_app.py       # another port
"""
import os
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _open_when_ready(url: str):
    """Open the browser only once the server answers (loading the road network takes 10-60 s)."""
    for _ in range(240):
        try:
            urllib.request.urlopen(url + "/api/health", timeout=1)
            print(f"Ready: {url}  (if you see the old design, press Command+Shift+R)", flush=True)
            if not os.environ.get("NO_BROWSER"):
                webbrowser.open(url)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.5)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8001"))
    url = f"http://localhost:{port}"
    print(f"Loading the Chandigarh road network... the browser opens at {url} when it's ready", flush=True)
    Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("csafe.api.server:app", host="127.0.0.1", port=port, log_level="warning")

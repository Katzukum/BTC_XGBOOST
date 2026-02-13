import os
import sys
import eel

from src.dashboard_service import DashboardService


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WEB_ROOT = os.path.join(PROJECT_ROOT, "web")

service = DashboardService(PROJECT_ROOT)


@eel.expose
def get_dashboard_snapshot():
    return service.get_snapshot()


@eel.expose
def ping():
    return {"status": "ok"}


def main():
    eel.init(WEB_ROOT)
    port = int(os.environ.get("EEL_PORT", "8080"))
    mode = os.environ.get("EEL_MODE", "chrome")

    # browser='default' works in environments where chrome is unavailable.
    eel.start("index.html", size=(1600, 980), port=port, mode=mode)


if __name__ == "__main__":
    try:
        main()
    except (SystemExit, KeyboardInterrupt):
        sys.exit(0)

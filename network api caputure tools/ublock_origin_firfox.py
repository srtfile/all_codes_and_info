import os
import sys
import time
import platform
import subprocess
from pathlib import Path

# ── auto-install deps ────────────────────────────────────────────────────────
def ensure(pkg, import_as=None):
    name = import_as or pkg.replace("-", "_")
    try:
        __import__(name)
    except ImportError:
        print(f"Installing {pkg} ...")
        subprocess.check_call([
            sys.executable,
            "-m",
            "pip",
            "install",
            pkg,
            "-q",
            "--disable-pip-version-check"
        ])

ensure("selenium")
ensure("webdriver_manager")

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager

# ─────────────────────────────────────────────────────────────────────────────
# FIREFOX PROFILE LOADER
# ─────────────────────────────────────────────────────────────────────────────
def get_firefox_profile():

    if platform.system() == "Windows":
        base = os.path.join(os.environ["APPDATA"], "Mozilla", "Firefox")
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/Firefox")
    else:
        base = os.path.expanduser("~/.mozilla/firefox")

    ini = os.path.join(base, "profiles.ini")

    if not os.path.exists(ini):
        raise FileNotFoundError(f"profiles.ini not found:\n{ini}")

    profile_rel = None

    with open(ini, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("Default="):
                val = line.strip().split("=", 1)[1]

                if val not in ("0", "1"):
                    profile_rel = val
                    break

    if not profile_rel:
        raise Exception("Could not find Firefox default profile.")

    profile_path = os.path.normpath(
        os.path.join(base, profile_rel.replace("/", os.sep))
    )

    if not os.path.isdir(profile_path):
        raise FileNotFoundError(f"Profile folder missing:\n{profile_path}")

    return profile_path

# ─────────────────────────────────────────────────────────────────────────────
# CLOSE OLD FIREFOX
# ─────────────────────────────────────────────────────────────────────────────
def kill_firefox():

    print("Closing existing Firefox ...")

    if platform.system() == "Windows":
        os.system("taskkill /F /IM firefox.exe /T >nul 2>&1")
    else:
        os.system("pkill -9 -f firefox 2>/dev/null")

    time.sleep(3)

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():

    print("\n=== FIREFOX + UBLOCK ORIGIN LOADER ===\n")

    # get firefox profile
    profile_path = get_firefox_profile()

    print("Firefox Profile:")
    print(profile_path)

    # kill old firefox
    kill_firefox()

    # geckodriver
    print("\nDownloading GeckoDriver ...")

    gecko = GeckoDriverManager().install()

    print("GeckoDriver OK")

    # firefox options
    options = Options()

    # load REAL firefox profile
    options.add_argument("-profile")
    options.add_argument(profile_path)

    # launch
    print("\nLaunching Firefox with your real profile...")
    print("uBlock Origin will load automatically if installed.\n")

    service = FirefoxService(
        executable_path=gecko,
        log_output=subprocess.DEVNULL
    )

    driver = webdriver.Firefox(
        service=service,
        options=options
    )

    driver.maximize_window()

    # open a page
    driver.get("https://cinemaos.tech/player/1318447")

    print("Firefox is running.")
    print("Browser will NOT close automatically.")
    print("Close Firefox manually when finished.\n")

    # keep python alive forever
    try:
        while True:
            time.sleep(999999)

    except KeyboardInterrupt:
        print("\nPython stopped.")
        print("Firefox stays open until YOU close it manually.")

if __name__ == "__main__":
    main()
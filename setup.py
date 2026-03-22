import subprocess
import sys
import os
from pathlib import Path

def main():
    base = Path(__file__).resolve().parent

    # Install requirements
    print("[AXIOM] Installing dependencies...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(base / "requirements.txt")])

    # Install Playwright browsers
    print("[AXIOM] Installing Playwright browsers...")
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])

    # Create config directory
    config_dir = base / "config"
    config_dir.mkdir(exist_ok=True)

    print("\n✅ Setup complete!")
    print("Run: python main.py")

if __name__ == "__main__":
    main()

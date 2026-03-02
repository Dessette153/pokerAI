"""
run_ui.py - Entry point for the Poker AI Web UI
Usage: python run_ui.py
Then open http://localhost:5000 in your browser.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as cfg
from app.ui.server import socketio, app

if __name__ == '__main__':
    print(f"Starting Poker AI UI at http://{cfg.UI_HOST}:{cfg.UI_PORT}")
    print("Open your browser and navigate to the URL above.")
    print("Press Ctrl+C to stop.\n")
    socketio.run(
        app,
        host=cfg.UI_HOST,
        port=cfg.UI_PORT,
        debug=False,
        allow_unsafe_werkzeug=True
    )

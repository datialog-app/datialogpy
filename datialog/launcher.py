"""
Datialog launcher — system tray + FastAPI server
Author: Ivan Pastor Sanz · CC BY-NC 4.0
"""

import os
import sys
import time
import signal
import threading
import webbrowser
import subprocess
from pathlib import Path

def launch(port: int = 8080, no_tray: bool = False, no_browser: bool = False):
    """
    Launch Datialog — starts the FastAPI server and opens the browser.
    Shows a system tray icon for easy control.
    
    Args:
        port: Port number (default 8080)
        no_tray: Disable system tray icon
        no_browser: Don't open browser automatically
    """
    import uvicorn
    from datialog.server import app

    url = f"http://127.0.0.1:{port}"
    
    # Server thread
    server_started = threading.Event()
    stop_event = threading.Event()
    
    def run_server():
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        
        # Patch startup to signal when ready
        original_startup = server.startup
        async def patched_startup(*args, **kwargs):
            await original_startup(*args, **kwargs)
            server_started.set()
        server.startup = patched_startup
        
        server.run()
    
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()
    
    # Wait for server to be ready
    print(f"  Iniciando Datialog en {url} ...")
    server_started.wait(timeout=10)
    time.sleep(0.3)
    
    # Open browser
    if not no_browser:
        webbrowser.open(url)
    
    if no_tray or not _tray_available():
        # Simple terminal mode
        print(f"  Datialog corriendo en {url}")
        print(f"  Pulsa Ctrl+C para detener.")
        try:
            while not stop_event.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n  Datialog detenido.")
    else:
        # System tray mode
        _run_tray(url, stop_event)


def _tray_available() -> bool:
    try:
        import pystray
        from PIL import Image
        return True
    except ImportError:
        return False


def _run_tray(url: str, stop_event: threading.Event):
    """Run system tray icon."""
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    
    # Create icon image
    icon_img = _create_icon()
    
    tray_icon = None
    
    def open_browser(icon, item):
        webbrowser.open(url)
    
    def stop_server(icon, item):
        icon.stop()
        stop_event.set()
        print("\n  Datialog detenido.")
        os._exit(0)
    
    menu = pystray.Menu(
        pystray.MenuItem("📊 Abrir Datialog", open_browser, default=True),
        pystray.MenuItem(f"🌐 {url}", lambda i, it: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("⏹ Detener y salir", stop_server),
    )
    
    tray_icon = pystray.Icon(
        name="Datialog",
        icon=icon_img,
        title="Datialog — Natural AI Data Explorer",
        menu=menu
    )
    
    print(f"  Datialog corriendo en {url}")
    print(f"  Icono en la bandeja del sistema. Clic derecho para opciones.")
    
    tray_icon.run()


def _create_icon() -> "Image":
    """Create a simple Datialog icon for the system tray."""
    from PIL import Image, ImageDraw, ImageFont
    
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Background circle
    draw.ellipse([2, 2, size-2, size-2], fill=(30, 77, 183, 255))
    
    # Letter D
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font = ImageFont.load_default()
    
    draw.text((18, 12), "D", fill=(255, 255, 255, 255), font=font)
    
    return img

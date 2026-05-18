# Datialog — Natural AI Data Explorer
# Autor: Ivan Pastor Sanz
# Año: 2025
# Licencia: CC BY-NC 4.0
# Web: datialog.app

import os
import sys
import json
import uuid
import hashlib
import platform
import requests
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
LICENSE_FILE = Path.home() / ".datialog" / "license.json"
ACTIVATION_SERVER = os.environ.get("DATIALOG_LICENSE_SERVER", "https://datialog-license-server-production.up.railway.app")
GRACE_DAYS = 3  # Days to work offline after last successful validation
APP_VERSION = "1.1.0"

# ── Machine fingerprint ───────────────────────────────────────────────────────
def get_machine_id() -> str:
    """Generate a unique machine fingerprint based on hardware info."""
    components = [
        platform.node(),           # hostname
        platform.machine(),        # architecture
        platform.processor(),      # CPU
        str(uuid.getnode()),       # MAC address
    ]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

# ── License file ─────────────────────────────────────────────────────────────
def load_license() -> dict:
    """Load license from local file."""
    if LICENSE_FILE.exists():
        try:
            return json.loads(LICENSE_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_license(data: dict):
    """Save license to local file."""
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(json.dumps(data, indent=2))

# ── Validation ────────────────────────────────────────────────────────────────
def validate_license(key: str = None) -> dict:
    """
    Validate license key.
    Returns: {"valid": bool, "plan": str, "expires": str, "message": str}
    """
    local = load_license()
    machine_id = get_machine_id()

    # Use stored key if none provided
    if not key:
        key = local.get("key", "")

    if not key:
        return {"valid": False, "message": "No hay licencia activada."}

    # Try online validation first
    try:
        resp = requests.post(
            f"{ACTIVATION_SERVER}/v1/license/validate",
            json={
                "key": key,
                "machine_id": machine_id,
                "version": APP_VERSION,
                "platform": platform.system(),
            },
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("valid"):
                # Save validated license locally
                save_license({
                    "key": key,
                    "machine_id": machine_id,
                    "plan": data.get("plan", "pro"),
                    "expires": data.get("expires", ""),
                    "email": data.get("email", ""),
                    "last_check": datetime.now().isoformat(),
                })
                return {"valid": True, "plan": data.get("plan", "pro"),
                        "expires": data.get("expires", ""), "message": "Licencia válida"}
            else:
                return {"valid": False, "message": data.get("message", "Licencia inválida")}
        elif resp.status_code == 403:
            return {"valid": False, "message": "Licencia ya activada en otro dispositivo."}
    except requests.RequestException:
        # Offline — check grace period
        if local.get("key") == key and local.get("machine_id") == machine_id:
            last_check = local.get("last_check", "")
            if last_check:
                try:
                    days_offline = (datetime.now() - datetime.fromisoformat(last_check)).days
                    if days_offline <= GRACE_DAYS:
                        return {"valid": True, "plan": local.get("plan", "pro"),
                                "expires": local.get("expires", ""),
                                "message": f"Modo offline (quedan {GRACE_DAYS - days_offline} días)"}
                except Exception:
                    pass
        return {"valid": False, "message": "Sin conexión y sin licencia válida en caché."}

    return {"valid": False, "message": "Error validando licencia."}

def activate_license(key: str) -> dict:
    """Activate a new license key on this machine."""
    return validate_license(key)

def get_license_info() -> dict:
    """Get current license info without re-validating."""
    local = load_license()
    if not local:
        return {"activated": False, "plan": None, "email": None, "expires": None}
    return {
        "activated": True,
        "key": local.get("key", "")[:8] + "****",  # masked
        "plan": local.get("plan"),
        "email": local.get("email"),
        "expires": local.get("expires"),
        "machine_id": local.get("machine_id", "")[:8] + "...",
    }

# ── CLI usage ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) > 1:
        key = sys.argv[1]
        print(f"Activando licencia: {key[:8]}****")
        result = activate_license(key)
        print(result["message"])
        sys.exit(0 if result["valid"] else 1)
    else:
        result = validate_license()
        print(json.dumps(result, indent=2, ensure_ascii=False))

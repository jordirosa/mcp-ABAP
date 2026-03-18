import os

from dotenv import load_dotenv
import requests

# Cargar variables de entorno desde archivo .env
load_dotenv()

APP_CONFIG = {
    "server": os.getenv("SAP_SERVER"),
    "user": os.getenv("SAP_USER"),
    "password": os.getenv("SAP_PASSWORD"),
    "client": os.getenv("SAP_CLIENT"),
    "language": os.getenv("SAP_LANGUAGE", "EN"),
    "verify_ssl": os.getenv("SAP_VERIFY_SSL", "false").lower() in ("true", "1", "yes")
}

# Validar que todas las variables necesarias estén configuradas
required_keys = ["server", "user", "password", "client"]
missing_keys = [key for key in required_keys if not APP_CONFIG[key]]

if missing_keys:
    raise ValueError(
        f"Faltan las siguientes variables de entorno: {', '.join(missing_keys.upper())}. "
        f"Por favor, configura el archivo .env correctamente."
    )

SESSION: requests.Session | None = None
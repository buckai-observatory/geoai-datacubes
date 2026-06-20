# config.py
import os

from sentinelhub import SHConfig

try:
    from dotenv import load_dotenv, find_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    load_dotenv = None
    find_dotenv = None


def get_config(client_id, client_secret, instance_id):
    """
    Returns Sentinel Hub configuration object.
    """
    config = SHConfig()
    config.sh_client_id = client_id
    config.sh_client_secret = client_secret
    config.instance_id = instance_id
    return config


def get_config_from_env():
    """
    Build a Sentinel Hub configuration object from environment variables.

    Loads a local ``.env`` file (searched for at the repo root or the
    pipeline directory) and reads:

        SH_CLIENT_ID      (required)
        SH_CLIENT_SECRET  (required)
        SH_INSTANCE_ID    (optional, defaults to "")

    Raises a ``RuntimeError`` with setup instructions if the required
    credentials are missing.
    """
    if load_dotenv is not None and find_dotenv is not None:
        load_dotenv(find_dotenv())

    client_id = os.environ.get("SH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SH_CLIENT_SECRET", "").strip()
    instance_id = os.environ.get("SH_INSTANCE_ID", "").strip()

    missing = [
        name
        for name, value in (
            ("SH_CLIENT_ID", client_id),
            ("SH_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing required Sentinel Hub credentials: "
            + ", ".join(missing)
            + ".\n\n"
            "To fix this:\n"
            "  1. Copy '.env.example' (at the repo root) to '.env' in the same\n"
            "     folder, then open '.env' and fill in your credentials.\n"
            "  2. You can get FREE Sentinel Hub credentials by registering at the\n"
            "     Copernicus Data Space Ecosystem:\n"
            "         https://dataspace.copernicus.eu/\n"
            "     Then create an OAuth client in the Sentinel Hub dashboard:\n"
            "         https://shapps.dataspace.copernicus.eu/dashboard/\n"
            "         (User settings -> OAuth clients -> \"Create new\")\n"
            "  3. Paste the client id into SH_CLIENT_ID and the secret into\n"
            "     SH_CLIENT_SECRET. SH_INSTANCE_ID is optional and may be left blank.\n"
        )

    return get_config(client_id, client_secret, instance_id)

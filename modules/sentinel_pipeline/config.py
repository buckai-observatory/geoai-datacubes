# config.py
from sentinelhub import SHConfig

def get_config(client_id, client_secret, instance_id):
    """
    Returns Sentinel Hub configuration object.
    """
    config = SHConfig()
    config.sh_client_id = client_id
    config.sh_client_secret = client_secret
    config.instance_id = instance_id
    return config

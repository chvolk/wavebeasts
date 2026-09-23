"""Advisory client versions; custom integrations are never forced to update."""
import re
from django.utils import timezone
from . import appversion

LISTENER_VERSION = '1.1.0'

def parts(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}',value):
        return None
    return tuple(map(int,value.split('.')))

def report(node, bundle):
    client=bundle.get('client') if isinstance(bundle,dict) else None
    if not isinstance(client,dict):return
    app=client.get('id','')
    version=client.get('app_v','')
    if not isinstance(app,str) or not isinstance(version,str):return
    node.client_app=app[:64];node.client_version=version[:32];node.client_reported_at=timezone.now()
    node.save(update_fields=['client_app','client_version','client_reported_at'])

def status(node):
    if node.kind == "browser":
        return {"managed": True, "update_available": False}
    latest={'wavebeast-node':LISTENER_VERSION,'wavebeast-engine':appversion.VERSION_NAME}.get(node.client_app)
    installed=parts(node.client_version)
    return {'installed':node.client_version,'latest':latest or '',
            'unknown':not node.client_app or bool(latest and not installed),
            'update_available':bool(latest and (not installed or installed<parts(latest))),
            'custom':bool(node.client_app and not latest)}

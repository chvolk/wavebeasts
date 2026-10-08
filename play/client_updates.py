"""Official client compatibility policy; custom integrations keep their own versions."""
import re
from django.utils import timezone
from . import appversion

LISTENER_VERSION = '1.2.0'
MIN_LISTENER_VERSION = '1.1.0'
MIN_ENGINE_VERSION = '0.12.15'
MIN_ENGINE_CODE = 34

def parts(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{1,5}\.\d{1,5}\.\d{1,5}',value):
        return None
    return tuple(map(int,value.split('.')))

def report(node, bundle):
    client=bundle.get('client') if isinstance(bundle,dict) else None
    if not isinstance(client,dict):return
    app=client.get('id','')
    if app == 'app' and client.get('app') == 'wavebeast-app':
        app = 'wavebeast-engine'  # legacy standalone GUI signature
    version=client.get('app_v','')
    if not isinstance(app,str) or not app:return
    if not isinstance(version,str):version=""
    node.client_app=app[:64];node.client_version=version[:32];node.client_reported_at=timezone.now()
    node.save(update_fields=['client_app','client_version','client_reported_at'])

def status(node):
    if node.kind == "browser":
        return {"managed": True, "update_available": False}
    latest={'wavebeast-node':LISTENER_VERSION,'wavebeast-engine':appversion.VERSION_NAME}.get(node.client_app)
    minimum={"wavebeast-node":MIN_LISTENER_VERSION,"wavebeast-engine":MIN_ENGINE_VERSION}.get(node.client_app)
    installed=parts(node.client_version)
    return {'installed':node.client_version,'latest':latest or '',
            'minimum':minimum or '',
            'update_required':bool(minimum and (not installed or installed<parts(minimum))),
            'unknown':not node.client_app or bool(latest and not installed),
            'update_available':bool(latest and (not installed or installed<parts(latest))),
            'custom':bool(node.client_app and not latest)}

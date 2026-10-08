"""Premium manual browser scanning. Accepts derived signals, never image files."""
import json
import math
import re
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from .models import Node, Wallet, Snapshot

@login_required
def page(request):
    from django.core.paginator import Paginator
    from urllib.parse import urlencode
    from .views import _wallet, _cull_wilds, beast_filter_json, _owned_drives
    wallet = _wallet(request.user)
    node = request.user.nodes.filter(kind='browser').first()
    _cull_wilds(request.user)
    finds = list(request.user.beasts.filter(status='wild').select_related('node'))
    rarities = ['common', 'uncommon', 'rare', 'epic', 'legendary']
    types = ['ember', 'tide', 'leaf', 'spark', 'stone', 'gale', 'frost', 'shade', 'lumen']
    filters = {k: request.GET.get(k, '') for k in ['search', 'rarity', 'type', 'sort']}
    finds = [b for b in finds if
             (not filters['search'] or filters['search'].lower() in b.name.lower()) and
             (not filters['rarity'] or b.rarity == filters['rarity']) and
             (not filters['type'] or filters['type'] in (b.species_json or {}).get('types', []))]
    sort_keys = {'rarity': lambda b: -rarities.index(b.rarity) if b.rarity in rarities else 1,
                 'type': lambda b: b.types_display, 'level': lambda b: -b.level,
                 'name': lambda b: b.name.lower()}
    if filters['sort'] in sort_keys:
        finds.sort(key=sort_keys[filters['sort']])
    page = Paginator(finds, 20).get_page(request.GET.get('page'))
    for beast in page:
        beast.filter_json = beast_filter_json(beast)
    snapshots = list(Snapshot.objects.filter(node__user=request.user, outcome='resource')
                     .select_related('node').order_by('-at', '-id')[:100]) if wallet.subscribed else []
    response = render(request, 'scanner.html', {
        'nav': 'scan', 'premium': wallet.subscribed,
        'cooldown': node.seconds_until_ready() if node else 0,
        'finds': page.object_list, 'find_page': page, 'snapshots': snapshots,
        'filters': filters, 'rarities': rarities, 'types': types,
        'page_query': urlencode(filters), 'catch_drives': _owned_drives(request.user),
        'discovery_msg': request.session.pop('discovery_msg', ''),
    })
    response['Cache-Control'] = 'private, no-store'
    return response


def signals_only(data):
    if not isinstance(data, dict) or set(data) != {'signals'} or not isinstance(data['signals'], list):
        raise ValueError('Expected derived signals only')
    signals = data['signals']
    if not 1 <= len(signals) <= 6:
        raise ValueError('Add text, a photo hash, or a barcode first')
    seen = set()
    for s in signals:
        if not isinstance(s, dict) or set(s) != {'kind', 'strength', 'value'} or not isinstance(s['value'], dict):
            raise ValueError('Invalid signal')
        kind, v = s['kind'], s['value']
        strength = s['strength']
        if not isinstance(strength, (int, float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
            raise ValueError('Invalid signal strength')
        if kind == 'code':
            if set(v) != {'symbology', 'data'} or v['symbology'] not in ('manual', 'barcode') or not isinstance(v['data'], str) or not 1 <= len(v['data']) <= 4096 or v['data'].startswith('data:'):
                raise ValueError('Invalid code')
            slot = 'text' if v['symbology'] == 'manual' else 'camera'
        elif kind == 'image_features':
            if set(v) != {'phash', 'palette', 'dims'} or not isinstance(v['phash'], str) or not re.fullmatch('[0-9a-f]{16}', v['phash']):
                raise ValueError('Only a local image hash is accepted')
            if not isinstance(v['palette'], list) or not 1 <= len(v['palette']) <= 6 or any(not isinstance(c, list) or len(c) != 3 or any(type(n) is not int or not 0 <= n <= 255 for n in c) for c in v['palette']):
                raise ValueError('Invalid palette')
            if not isinstance(v['dims'], list) or len(v['dims']) != 2 or any(type(n) is not int or not 1 <= n <= 16384 for n in v['dims']):
                raise ValueError('Invalid image dimensions')
            slot = 'camera'
        elif kind == 'scalar':
            if set(v) != {'metric', 'n'} or v['metric'] not in ('orientation_alpha', 'orientation_beta', 'orientation_gamma') or not isinstance(v['n'], (int, float)) or not math.isfinite(v['n']) or not -360 <= v['n'] <= 360:
                raise ValueError('Invalid browser sensor reading')
            slot = v['metric']
        else:
            raise ValueError('Unsupported browser signal')
        if slot in seen:
            raise ValueError('Use one text input and one camera input')
        seen.add(slot)
    if not seen.intersection({'text', 'camera'}):
        raise ValueError('Add a code or capture a photo first')
    return signals


@login_required
@require_POST
@transaction.atomic
def scan(request):
    from .views import _wallet, submit_snapshot, PAID_NODE_LIMIT
    _wallet(request.user)
    wallet = Wallet.objects.select_for_update().get(user=request.user)
    if not wallet.subscribed:
        return JsonResponse({'error': 'Browser scanning requires Premium'}, status=402)
    if request.content_type != 'application/json' or len(request.body) > 16384:
        return JsonResponse({'error': 'Send compact JSON signals, not images'}, status=400)
    try:
        signals = signals_only(json.loads(request.body))
    except (ValueError, TypeError, KeyError):
        return JsonResponse({'error': 'Invalid scan. Send one text input, one camera code or image hash, and optional sensor readings.'}, status=400)
    # One persistent browser node per account means opening tabs does not reset cooldown.
    node = request.user.nodes.select_for_update().filter(kind='browser').first()
    if node is None:
        if request.user.nodes.count() >= PAID_NODE_LIMIT:
            return JsonResponse({'error': 'Node limit reached. Remove an unused node before adding the browser scanner.'}, status=409)
        node = Node.objects.create(user=request.user, kind='browser', name='Browser scanner')
    response = submit_snapshot(request, node, {'schema': 'wavebeast.scanbundle', 'v': 1, 'signals': signals})
    if response.status_code == 200:
        wallet.refresh_from_db()
        payload = json.loads(response.content)
        payload['wallet'] = {'shards': wallet.shards, 'cores': wallet.cores}
        response = JsonResponse(payload)
    response['Cache-Control'] = 'private, no-store'
    return response

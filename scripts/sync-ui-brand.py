#!/usr/bin/env python3
"""Copy shared brand assets to the sibling engine, or verify they match with --check.
Usage: python scripts/sync-ui-brand.py [--engine /path/to/wavebeast] [--check]
The site is the source of truth; the engine embeds its own copy for offline play.
"""
import argparse
from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--engine', type=Path, default=root.parent / 'wavebeast')
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
source = root / 'play/static/brand'
target = args.engine / 'internal/api/web/brand'
if not (args.engine / 'go.mod').exists():
    parser.error('Engine checkout not found; pass --engine')
if args.check:
    differences = [str(p.relative_to(source)) for p in source.rglob('*') if p.is_file() and
                   (not (target / p.relative_to(source)).exists() or p.read_bytes() != (target / p.relative_to(source)).read_bytes())]
    if differences:
        raise SystemExit('Brand assets differ: ' + ', '.join(differences))
    print('Shared brand assets match.')
else:
    shutil.copytree(source, target, dirs_exist_ok=True)
    print('Copied shared brand assets to', target)

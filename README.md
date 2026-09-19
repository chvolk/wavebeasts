# WaveBeasts (site)

The account + multiplayer hub for [WaveBeast](../wavebeast). Basic Django username/password auth, a
network of **listener nodes** that push rate-limited sensor **snapshots** to your profile (speed the
cadence up with in-game currency), a trade market and battles (WIP).

Nodes are slim — they only assemble a `ScanBundle` and POST it to `/api/snapshot` with a node token. The
**WaveBeast Go engine runs headless as the stateless resolver** (`WAVEBEAST_RESOLVER`) so all generation
and battle rules live in exactly one place.

## Dev

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    export WAVEBEAST_RESOLVER=http://bishop.home:8777   # a running wavebeast engine
    python manage.py migrate
    python manage.py runserver

## Deploy (Railway)

Set `SECRET_KEY`, `DEBUG=0`, `DATABASE_URL` (Postgres), `WAVEBEAST_RESOLVER` (co-located engine),
`ALLOWED_HOSTS`. `Procfile` runs migrations + gunicorn.

## Roadmap

P3 accounts + nodes + snapshots + trade market + async (Super Auto Pets) battles · P4 live Stadium PvP.

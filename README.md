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

### Field journals, activity, and node health (0.12.17)

- Private account activity uses atomic receipts with currency/item deltas and resulting balances. The website and selected account host in the app share this history. Existing balances form the opening entry; older transactions are not reconstructed.
- Beast journals retain discovery categories, stable descriptive traits, up to 100 memories, battle totals, favorites, nicknames, and private notes. Favorites block release; private annotations reset on account trades. Collection goals measure currently owned beasts without additional rewards.
- `/api/nodes/status` separates check-ins from scan attempts and successful scans. Listener 1.2.0 and running account-linked engines send two-minute heartbeats without sensor acquisition or rewards. Passive scanning remains at least 30 minutes apart.
- Custom integrations can read `/api/activity?before=&kind=`, `/api/beast/{id}`, and update `/api/beast/profile` with their node token. See the API wiki for fields and limits.

Validation: Django suite (129 tests, 3 existing skips), Go suite, listener cadence checks, and Chromium UI checks at 390px and 1440px, including account relay pagination and shared journals. No physical mobile device was available for this validation.

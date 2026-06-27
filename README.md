# Ink

A multi-tenant product backend that renders a daily, hand-cut **Matisse-style
B&W artwork** — with date, weather, and an inspiring "on this day" event — onto
Seeed Studio TRMNL 7.5" e-ink frames running ESPHome.

Users self-serve: create an account, pair their frame with an on-screen code,
set preferences in the app, and (optionally) bring their own OpenAI API key.

```
Ink app (PWA)                     TRMNL frame (ESPHome)
   │  accounts, pairing,            │  wake / KEY1
   │  preferences, API key          ▼
   ▼                          GET /media/current/<mac>.png ──┐
Backend  (FastAPI, one host)                                 │
  ├─ /api/app/*   accounts · pairing · prefs · key mgmt       │ 1-bit PNG
  ├─ /api/setup,/api/display   BYOS device contract ◀─────────┘
  ├─ daily scheduler → weather + holidays + event + image + dither
  └─ secrets: platform key, master encryption key (env only)
```

## Key ideas
- **Multi-tenant**: accounts own devices; one account can hold many frames; a
  frame is bound to an account by a pairing code shown on its screen.
- **API-key abstraction** (`backend/keys.py`): generation runs on **your
  platform key** by default. An account can set **its own key** (encrypted at
  rest with Fernet). You can flip an account to **own-key-required** remotely via
  an admin endpoint; the app then prompts that user to add their key.
- **Onboarding on the device**: WiFi via the ESPHome captive portal; account
  binding via the pairing code → app. No per-device flashing — every frame runs
  identical firmware and is identified by its MAC.
- **Factory reset**: hold KEY3 ~5s to wipe WiFi + local state and re-onboard;
  "Remove this frame" in the app unbinds it and clears its preferences so it can
  be re-assigned to a new account.

## Repository layout
```
artframe/            provider-agnostic generation pipeline (weather, holidays,
                     event + image prompts, Floyd-Steinberg dithering)
backend/             FastAPI multi-tenant server
  config.py          env settings (platform key, master key, admin token)
  crypto.py          Fernet encryption for per-account keys
  keys.py            effective-key resolution + key_status
  auth.py            account bearer-token auth
  db.py models.py repositories.py artwork_repo.py
  device_api.py      /api/setup, /api/display, /api/log (BYOS contract)
  app_api.py         accounts, pairing, prefs, key mgmt, admin
  media_api.py       serves the image / pairing splash per device state
  generation.py      resolve key → pipeline → store
  scheduler.py       daily per-device generation
  splash.py          pairing / connect splash PNGs
static/              the Ink PWA (served at /app)
firmware/            ESPHome config (trmnl-artframe.yaml)
```

## Quick start (local)
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt    # Windows
cp .env.example .env
.venv/Scripts/python -m backend.crypto                     # prints a MASTER_ENCRYPTION_KEY
# fill .env: PLATFORM_OPENAI_API_KEY, MASTER_ENCRYPTION_KEY, ADMIN_TOKEN, PUBLIC_BASE_URL
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```
- App: `http://localhost:8000/app/`  ·  Health: `/healthz`
- Tests: `.venv/Scripts/python -m pytest` (19 tests, no network/keys)

## Configuration (env / `.env`)
| Variable | Purpose |
|---|---|
| `PUBLIC_BASE_URL` | HTTPS URL the device + app reach the backend at |
| `PLATFORM_OPENAI_API_KEY` | Your default key (the payer until users bring their own) |
| `MASTER_ENCRYPTION_KEY` | Fernet key for encrypting per-account keys (`python -m backend.crypto`) |
| `ADMIN_TOKEN` | Guards the "require own key" admin endpoint |
| `OPENAI_IMAGE_MODEL` / `OPENAI_TEXT_MODEL` | Pinned model ids |
| `DATA_DIR` | SQLite + images location |

## Deploy
**Render (one click):** New + → Blueprint → pick this repo (`render.yaml` is
included). After the first deploy, set `PLATFORM_OPENAI_API_KEY`, a
`MASTER_ENCRYPTION_KEY` (`python -m backend.crypto`), and `PUBLIC_BASE_URL` (the
URL Render gives you) in the service's Environment tab.

**Any other host:** `docker build -t ink . && docker run -p 8000:8000 -v ink-data:/data --env-file .env ink`, behind HTTPS.

Then set the firmware's `backend_base` to your `PUBLIC_BASE_URL` — see [FIRMWARE.md](FIRMWARE.md).

## Flipping a user to their own key (remote)
```bash
curl -X POST "$BASE/api/app/admin/accounts/<account_id>/require-own-key" \
     -H "X-Admin-Token: $ADMIN_TOKEN"
```
The user's app then shows "your own key is required" until they add one.

## Cost
Platform-key generation ≈ \$0.50–\$1.50/mo for a handful of daily frames;
weather/holiday APIs free; host \$0–6/mo. Per-user keys move generation cost to
the user.

## Notes
- **Deep sleep = no push**: "Regenerate today" appears on the frame at its next
  wake or a KEY1 press.
- **`gpt-image` model ids drift** — pin `OPENAI_IMAGE_MODEL` and verify before
  shipping.
- Auth is intentionally minimal (account bearer token). Email/password or
  magic-link can be layered into `backend/auth.py` without touching devices.

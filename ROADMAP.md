# Ink — Roadmap & decisions

Short record of decisions so we don't re-litigate them.

## Now (1–3 friends)
- Accounts = a device-stored bearer token (`backend/auth.py`). No real login.
  This is intentional and sufficient at this scale.
- Backend runs as one always-on process (FastAPI) with SQLite + local image
  storage. Hosting for friends: home machine, or a small cheap host (see SHIP.md).

## Next milestone — PROVE THE CORE (do before anything below)
1. **Live image generation** against a real OpenAI key — confirm the art renders
   and measure real time/cost. (No hardware needed; just a key in `.env`.)
2. **Hardware flash** of one frame — verify the pairing screen, the Wi-Fi-join
   QR, the power-aware sleep, and the on-panel render; calibrate `powered_voltage`.

## After the core is proven — Accounts & multi-user (DECIDED)
- **Auth: Supabase Auth** — "Sign in with Google" + email magic-link. Chosen over
  rolling our own (no password liability) and over plain tokens (no recovery /
  cross-device). Firebase/Clerk would also work; Supabase is preferred because it
  bundles the DB + Storage we'll adopt next.
- **Incremental rollout:**
  1. Auth first — add Supabase Google SSO; backend verifies the JWT; account keyed
     by the Google user id. Keep SQLite (only `auth.py` changes).
  2. DB/Storage later — migrate SQLite → Supabase Postgres and images → Supabase
     Storage (the repository layer keeps this contained). Enables a durable,
     shareable design-history gallery.
- The **frame is unaffected** by auth — it authenticates by MAC; pairing links it
  to whichever user is logged in.
- Each user generates their own images on the platform key by default, or their
  own key (already built: `backend/keys.py`).

## Later / maybe
- Native app (iOS+Android) only if we want the true "frame appears as an
  available device" BLE onboarding — not possible in a PWA. Today's two-scan
  flow (Wi-Fi-join QR + app QR) covers it cross-platform for free.

# Shipping Ink to 1–3 friends (free except OpenAI)

This is the practical checklist to take Ink from "code in a repo" to "frames on
your friends' walls." Everything here is free except the OpenAI image
generation. Estimated time: ~1–2 hours the first time.

---

## What you'll need (prerequisites)

**Accounts**
- [ ] **OpenAI account + API key** — the only thing that costs money. Confirm the
      key has access to the image model (`gpt-image-1`). This is your *platform
      key*; it pays for everyone until a friend opts into their own.
- [ ] **GitHub** — done; code is at https://github.com/tikel1/ink.
- [ ] A **host** for the backend (free options below).

**On your computer (to flash the frames)**
- [ ] Python 3.12
- [ ] ESPHome — `pip install esphome`
- [ ] A USB‑C cable and the **Seeed TRMNL 7.5" kit(s)** (1–3 of them)

**Per frame, before flashing — know these**
- [ ] The friend's **timezone** (e.g. `Asia/Jerusalem`)
- [ ] (Location and the daily generation hour are set later in the app, not at
      flash time)

---

## Step 1 — Get the backend running (free)

The backend must be **always‑on**, reachable over **HTTPS**, and keep its data
(accounts, pairings, images). Pick one path.

### Option A (recommended if you have an always‑on machine): home server + Tailscale Funnel — truly $0
Use any machine that stays on (an old laptop, a mini‑PC, a Raspberry Pi).
1. Clone + run the backend:
   ```bash
   git clone https://github.com/tikel1/ink && cd ink
   python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env          # fill it in — see Step 2
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
2. Expose it with a stable HTTPS URL (free, no domain, no card):
   ```bash
   # install Tailscale, then:
   tailscale funnel 8000
   ```
   This prints a permanent URL like `https://your-box.tailnet.ts.net`. That's
   your `PUBLIC_BASE_URL`.
- ✅ Free forever, data persists on local disk, stable HTTPS.
- ⚠️ Depends on that machine staying powered on and online.

### Option B (no spare machine): Fly.io
1. Install `flyctl`, `fly launch` in the repo (it detects the `Dockerfile`),
   add a 1 GB volume mounted at `/data`, set `min_machines_running = 1`.
2. Your URL is `https://<app>.fly.dev` → that's `PUBLIC_BASE_URL`.
- ✅ Reliable, persistent volume, very low effort.
- ⚠️ Requires a credit card; at this scale it's ~free (a dollar or two at most),
  not guaranteed $0.

### Don't use for the real thing
Render's **free** web service sleeps after 15 min and **wipes the disk** on
restart — you'd lose accounts, pairings, and images. Fine for a 10‑minute test,
not for friends' frames. (The included `render.yaml` uses the `starter` plan,
which has a persistent disk, ~$7/mo — only if you want a no‑maintenance cloud
host later.)

---

## Step 2 — Configure secrets (`.env`)

```ini
PUBLIC_BASE_URL=https://your-box.tailnet.ts.net   # from Step 1
PLATFORM_OPENAI_API_KEY=sk-...                     # your OpenAI key
MASTER_ENCRYPTION_KEY=                             # see below
ADMIN_TOKEN=pick-a-long-random-string              # guards the "require own key" action
OPENAI_IMAGE_MODEL=gpt-image-1
```
Generate the encryption key once and paste it in:
```bash
python -m backend.crypto      # prints a MASTER_ENCRYPTION_KEY
```
> `MASTER_ENCRYPTION_KEY` encrypts friends' own API keys at rest. If you ever
> lose it, those stored keys can't be decrypted (your platform key still works).

Restart the backend after editing `.env`.

---

## Step 3 — Smoke‑test the backend (2 min)

From any browser:
- [ ] `https://<your-url>/healthz` → `{"status":"ok"}`
- [ ] `https://<your-url>/app/` → the Ink app loads (sand screen, floating ink)
- [ ] In the app: **Get started** → it should create an account without error.

If `/healthz` works from your phone on mobile data (not your home WiFi), the
frames will be able to reach it too.

---

## Step 4 — Flash each frame

For each kit, edit the substitutions at the top of
`firmware/trmnl-artframe.yaml` (or pass per‑device), then flash over USB:
```yaml
substitutions:
  backend_base: "https://your-box.tailnet.ts.net"   # SAME as PUBLIC_BASE_URL
  timezone:  "Asia/Jerusalem"
  # idle_minutes / powered_voltage / powered_refresh_minutes have sane defaults
```
```bash
esphome run firmware/trmnl-artframe.yaml
```
All frames can use the same `backend_base`; each is identified automatically by
its WiFi MAC. On USB power a frame stays on; on battery it sleeps and wakes on
the button (KEY1).

---

## Step 5 — Onboard + pair (do this before gifting)

For each frame:
1. Power it on → it shows "Join WiFi: Ink Frame".
2. Hold the button → join the **Ink Frame** hotspot on your phone → enter the
   WiFi it will use (your WiFi for testing; the friend's WiFi if you know it).
3. The frame shows a **QR + 6‑digit code**.
4. **Scan the QR** with your phone camera (opens the app and pairs in one tap),
   or open `https://<your-url>/app/` → **Get started** → **Pair frame** → enter
   the code. Then set the friend's **location**, **wake hour**, and interests.
5. Tap **Regenerate** → in ~20–30s the app shows the first artwork. Press **KEY1**
   on the frame to pull it immediately (on USB power it also refreshes on its own).

---

## Step 6 — Hand off to each friend

Choose how friends control their frame:

- **Simplest (you manage everything):** keep all frames under *your* account.
  Friends just plug in at home. To change a setting, you do it in your app.
  - If a friend's home WiFi differs from where you tested: do a **factory reset**
    (hold **KEY3 ~5s**) before gifting, or have them redo Step 5 part 2 on their
    WiFi. The pairing/account stays intact through a WiFi reset.

- **Per‑friend accounts (each controls their own):** before gifting, open the
  frame in your app and tap **Remove frame** (this unbinds it and clears
  settings). Give the friend the app URL; they tap **Get started**, then **Pair
  frame** with the code shown on their screen after they connect WiFi.

Either way, generation runs on **your** OpenAI key by default. If you later want
a specific friend to pay for their own, flip them with the admin endpoint:
```bash
curl -X POST "$PUBLIC_BASE_URL/api/app/admin/accounts/<account_id>/require-own-key" \
     -H "X-Admin-Token: $ADMIN_TOKEN"
```
Their app will then prompt them to enter their own key.

---

## What it costs

| Item | Cost |
|---|---|
| Backend host | **$0** (home + Tailscale) or ~free (Fly) |
| Weather (Open‑Meteo), holidays (Hebcal, Nager) | **$0** |
| OpenAI image generation | ~**$0.01–0.04 per image/day per frame** |
| 3 frames, one image/day | ≈ **$1–4 / month**, all on your key |

---

## Honest status — verify these before you rely on it

- [ ] **Live OpenAI generation is unverified.** Everything has been tested with a
      stub. Run one real generation (Step 5 Regenerate) and look at the art on a
      real panel before gifting. This also tells you the true per‑image time/cost.
- [ ] **Firmware is unflashed.** The YAML is written from your original working
      config, but it hasn't been compiled/flashed or seen on hardware yet —
      including the KEY3 factory reset and the on‑panel render.
- [ ] **Auth is minimal** (an account = a token on the phone). Fine for friends;
      add real login before any wider release.
- [ ] **`gpt-image-1`** model id — confirm it's current for your OpenAI account.

# Running Ink on a Home Assistant OS Pi

Ink runs as a **local add-on** on your HA OS Pi, exposed to the internet over
HTTPS by a tunnel so your friends' frames (on other networks) can reach it.

```
Friend's frame ──HTTPS──▶  tunnel  ──▶  Ink add-on (:8000 on the Pi)
Pages app (HTTPS) ─────────┘
```

## 1. Install the add-on
1. On the Pi's Samba/SSH share, copy the `ha-addon/ink` folder into `/addons`
   so you have `/addons/ink/{config.yaml,Dockerfile,run.sh}`.
2. HA → **Settings → Add-ons → Add-on Store → ⋮ → Check for updates**. The
   **Ink** local add-on appears under "Local add-ons". Open it → **Install**
   (first build takes a few minutes on a Pi).
3. **Configuration** tab → fill in:
   - `platform_openai_api_key` — your OpenAI key
   - `master_encryption_key` — generate once: run `python -m backend.crypto`
     on any machine with the repo, paste the output
   - `admin_token` — any long random string
   - `public_base_url` — your tunnel URL from step 2 below (e.g.
     `https://ink.example.com`)
   - `app_url` — `https://tikel1.github.io/ink`
4. **Start** the add-on. Check the **Log** tab for "scheduler started".

## 2. Expose it over HTTPS (pick one)

**A. Cloudflare Tunnel — recommended if you own a domain.** Install the
community **Cloudflared** add-on, authenticate, and add a route mapping a
hostname to the Ink add-on, e.g. `ink.yourdomain.com → http://homeassistant.local:8000`.
Stable, automatic HTTPS, no open ports. Set `public_base_url` to that URL.

**B. Tailscale Funnel — no domain needed.** Install the **Tailscale** add-on,
log in, and enable **Funnel** for port `8000`. It gives a public
`https://<your-host>.ts.net`. Set `public_base_url` to that. (Verify the add-on
can funnel a non-HA port; if not, use option A.)

## 3. Point things at it
- **Firmware**: set `backend_base` in `firmware/trmnl-artframe.yaml` to your
  `public_base_url`, then flash.
- **App**: nothing to do — the frame's QR carries the server address, or set it
  in the app under Account → Ink server.

## Notes
- Data (accounts, pairings, images) persists in the add-on's `/data/store`.
- This add-on pulls the latest `main` at build time; rebuild the add-on to update.
- **Unverified on hardware** — this packaging is a best-effort starter. If the
  build or tunnel gives trouble, a $7 Render service is the fallback that needs
  no Pi/tunnel setup.

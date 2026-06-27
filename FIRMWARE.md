# Frame Firmware & Setup

Every frame runs the **same** standalone ESPHome firmware
([firmware/trmnl-artframe.yaml](firmware/trmnl-artframe.yaml)) pointed at your
backend. There is **nothing per-device to flash** — the frame identifies itself
by its WiFi MAC, and account binding happens later via a pairing code.

## Configure once, before flashing
```yaml
substitutions:
  backend_base: "https://frames.example.com"   # your PUBLIC_BASE_URL
  wake_hour: "6"
  timezone:  "Asia/Jerusalem"
```
Flash with `esphome run firmware/trmnl-artframe.yaml`.

## How it works
- On boot the frame waits for WiFi (captive-portal onboarding), then sets its
  image URL to `<backend_base>/media/current/<mac>.png` at runtime and fetches.
- The backend auto-registers an unknown MAC and returns a **pairing-code splash**
  until the frame is added to an account.
- Once paired, the backend returns the daily artwork and a `refresh_rate` equal
  to seconds-until-`wake_hour`, so the frame deep-sleeps until morning.

## Onboarding (what the user does)
1. Power on → screen shows `Join WiFi: Ink Frame`.
2. Hold the button ~5s → the frame becomes the `Ink Frame` hotspot.
3. Join it on a phone → captive portal → enter home WiFi.
4. The frame connects and shows a **6-digit pairing code + QR**.
5. In the Ink app: create an account, **Add a frame**, enter the code,
   set location / interests / etc. The first artwork appears on the next wake or
   a KEY1 press.

## Buttons
| Button | Pin | Action |
|---|---|---|
| KEY1 | GPIO2 | Refresh now (and wakes from deep sleep) |
| KEY2 | GPIO3 | Stay awake (cancel auto-sleep) |
| KEY3 | GPIO5 | Tap = sleep now · **hold 5s = factory reset** |

## Reset & re-assignment (your three requirements)
- **Forget WiFi + local state on the device** → hold KEY3 ~5s. This uses
  ESPHome's `factory_reset` button: it erases all saved preferences (including
  WiFi) and reboots into the onboarding captive portal.
- **Re-assign the account + forget old preferences** → in the app, open the
  frame and tap **Remove this frame**. The backend unbinds it, resets its
  preferences to defaults, and issues a new pairing code, so the frame
  immediately shows the pairing splash again and can be added to a new account.
- **Unique URL / account connection** is handled by the pairing code, not a
  typed URL — the device's identity is its MAC and one shared backend URL.

## Notes
- **HTTPS** required (`verify_ssl: false` skips cert pinning for the public
  image). `ota: platform: esphome` allows WiFi firmware updates later.
- **Battery**: one wake/day ≈ months per charge; voltage is logged from GPIO1.

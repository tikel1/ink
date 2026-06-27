# Frame Firmware & Setup

Every frame runs the **same** standalone ESPHome firmware
([firmware/trmnl-artframe.yaml](firmware/trmnl-artframe.yaml)) pointed at your
backend. There is **nothing per-device to flash** — the frame identifies itself
by its WiFi MAC, and account binding happens later via a pairing code.

## Configure once, before flashing
```yaml
substitutions:
  backend_base: "https://frames.example.com"   # your PUBLIC_BASE_URL
  timezone:  "Asia/Jerusalem"
  idle_minutes: "10"               # battery: sleep after this much idle time
  powered_voltage: "4.15"          # >= this reads as "on USB power" (calibrate)
  powered_refresh_minutes: "60"    # powered: how often to re-fetch the art
```
The daily generation *hour* is set per frame in the app, not here. Flash with
`esphome run firmware/trmnl-artframe.yaml`.

## How it works
- On boot the frame waits for WiFi (captive-portal onboarding), then sets its
  image URL to `<backend_base>/media/current/<mac>.png` at runtime and fetches.
- The backend auto-registers an unknown MAC and returns a **QR + pairing-code
  splash** until the frame is added to an account.
- **Power-aware behavior** (decided each boot from the battery rail voltage):
  - **On USB power** → the frame stays **on** and re-fetches the art every
    `powered_refresh_minutes`.
  - **On battery** → it shows the current art, then **deep-sleeps after
    `idle_minutes`** of no button activity. Press **KEY1** to wake; it re-fetches
    today's art, shows it, and sleeps again after the idle window. (KEY1 is the
    wake pin, so the frame is fully off in between — maximal battery life.)

## Onboarding (what the user does)
1. Power on → screen shows `Join WiFi: Ink Frame`.
2. Hold the button ~5s → the frame becomes the `Ink Frame` hotspot.
3. Join it on a phone → captive portal → enter home WiFi.
4. The frame connects and shows a **QR + 6-digit pairing code**.
5. **Scan the QR** (opens the Ink app and pairs in one tap), or open the app and
   type the code. Then set location / interests. The first artwork appears on the
   next refresh or a **KEY1** press.

## Buttons
| Button | Pin | Action |
|---|---|---|
| KEY1 | GPIO2 | Wake from sleep + refresh now |
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
- **Power detection is a voltage heuristic** (battery rail ≥ `powered_voltage`
  reads as "plugged in"). The XIAO board has no clean USB-sense pin, so calibrate
  `powered_voltage` against a real device — a freshly charged battery can read
  high while unplugged. Adjust if a battery frame won't sleep or a powered frame
  sleeps.
- **Battery life**: on battery it only wakes on KEY1, so it sips power between
  presses; expect months of standby on the 2000 mAh cell.

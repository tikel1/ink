"""Paired device: generation writes the image and the device fetches it."""
import io

from fastapi.testclient import TestClient
from PIL import Image

from backend import generation, repositories
from backend.main import app

client = TestClient(app)
DEVICE = "DD:EE:FF:00:11:22"


async def test_paired_device_generation_is_served(monkeypatch):
    # Pair a device to a fresh account.
    token = client.post("/api/app/account").json()["token"]
    client.get("/api/setup", headers={"ID": DEVICE})
    code = repositories.get_device(DEVICE).pairing_code
    client.post("/api/app/devices/pair", json={"pairing_code": code},
                headers={"Authorization": f"Bearer {token}"})

    # Stub the pipeline so no network/key is needed.
    from artframe.pipeline.generate import ArtworkResult

    def fake_png() -> bytes:
        buf = io.BytesIO()
        Image.new("1", (800, 480), 1).save(buf, format="PNG")
        return buf.getvalue()

    from artframe.timeutil import now_in_tz

    async def fake_generate(settings, config):
        # Use today's date in the device tz so /api/display finds it.
        today = now_in_tz(config.tz).date().isoformat()
        return ArtworkResult(
            device_id=config.id, date=today, image_png=fake_png(),
            event_text_en="Test event", event_text_he=None,
            weather_summary="clear, 25°C",
        )

    monkeypatch.setattr(generation, "generate_artwork", fake_generate)

    device = repositories.get_device(DEVICE)
    assert await generation.generate_for_device(device) is True

    # The device now fetches a real PNG (not the pairing splash).
    img = client.get(f"/media/current/{DEVICE}.png")
    assert img.status_code == 200
    with Image.open(io.BytesIO(img.content)) as im:
        assert im.size == (800, 480)

    # /api/display returns a sleep-until-morning refresh, not the retry cadence.
    disp = client.get("/api/display", headers={"ID": DEVICE}).json()
    assert disp["refresh_rate"] != 300

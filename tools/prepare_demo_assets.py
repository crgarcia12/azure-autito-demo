from pathlib import Path

import httpx
from PIL import Image

from tools.cloud import ROOT
from fleet.demo_case import PHOTO


def main():
    with Image.open(PHOTO) as supplied:
        supplied.verify()
    source = ROOT / ".local" / "bumper-damage-original.jpg"
    if not source.exists():
        response = httpx.get("https://upload.wikimedia.org/wikipedia/commons/d/d7/Jetta_Mk._IV_Bumper_Damage.jpg", timeout=90)
        response.raise_for_status()
        source.write_bytes(response.content)
    destination = ROOT / "static" / "demo-assets"
    destination.mkdir(exist_ok=True)
    with Image.open(source) as image:
        # A separate close-up and overview make both the straightforward and inspection-required paths exercisable.
        image.crop((360, 710, 1420, 1060)).save(destination / "bumper-detail.jpg", quality=92)
        image.save(destination / "bumper-overview.jpg", quality=88)
    dent = ROOT / ".local" / "foundry-bumper-evidence.jpg"
    if not dent.exists():
        response = httpx.get("https://www.publicdomainpictures.net/pictures/500000/velka/dented-car-bumper.jpg", timeout=90)
        response.raise_for_status()
        dent.write_bytes(response.content)
    with Image.open(dent) as image:
        image.convert("RGB").save(destination / "bumper-dent.jpg", quality=92)
    print(f"Primary upload photo: {PHOTO}. Historical public-domain test photographs are also available.")


if __name__ == "__main__":
    main()

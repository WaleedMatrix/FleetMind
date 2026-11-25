"""Fetch the attributed UCI data and verify the exact CSV used by FleetMind."""

import io
from hashlib import sha256
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile

URL = "https://archive.ics.uci.edu/static/public/601/ai4i+2020+predictive+maintenance+dataset.zip"
EXPECTED = "dc6630cd9b1f0f853922fad78a1b6436570d3f1ec863f1dd5c4340ac56bc8a8e"
DATASET = Path("data/raw/ai4i2020.csv")


def main():
    if DATASET.exists():
        csv = DATASET.read_bytes()
    else:
        with urlopen(URL, timeout=30) as response:
            archive = response.read(2_000_001)
        if len(archive) > 2_000_000:
            raise ValueError("Dataset archive exceeds 2 MB.")
        with ZipFile(io.BytesIO(archive)) as zipfile:
            info = zipfile.getinfo("ai4i2020.csv")
            if info.file_size > 2_000_000:
                raise ValueError("Dataset CSV exceeds 2 MB.")
            csv = zipfile.read(info)
    if sha256(csv).hexdigest() != EXPECTED:
        raise ValueError("The dataset differs from the original training CSV.")
    DATASET.parent.mkdir(exist_ok=True, parents=True)
    if not DATASET.exists():
        with DATASET.open("xb") as stream:
            stream.write(csv)
    print(f"Verified {DATASET} against the frozen dataset hash.")


if __name__ == "__main__":
    main()

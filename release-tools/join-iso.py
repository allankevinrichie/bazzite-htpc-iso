"""Reassemble Bazzite ISO parts and verify SHA-256. Requires Python 3."""
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile

ISO = "bazzite-htpc-amd64.iso"
PART = re.compile(r"^" + re.escape(ISO) + r"\.part([0-9]{3})$")
BUF = 8 * 1024 * 1024


def sha_line(data, allowed):
    line = re.fullmatch(r"([0-9a-f]{64})  ([a-zA-Z0-9._-]+)", data)
    if not line or not allowed(line[2]):
        raise ValueError(f"Invalid SHA-256 manifest line: {data!r}")
    return line[1], line[2]


def join(directory):
    digest, _ = sha_line((directory / "SHA256SUMS").read_text().strip(),
                         lambda name: name == ISO)
    parts = (directory / "PARTS.sha256").read_text().splitlines()
    if not 1 <= len(parts) <= 990:
        raise ValueError("Invalid number of parts")
    output = directory / ISO
    if output.exists():
        raise FileExistsError(f"Will not overwrite {output}")
    fd, name = tempfile.mkstemp(prefix=ISO + ".", suffix=".tmp", dir=directory)
    tmp = Path(name)
    full = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as out:
            for i, line in enumerate(parts, 1):
                expected, part = sha_line(line, PART.fullmatch)
                if part != f"{ISO}.part{i:03d}":
                    raise ValueError(f"Missing or unordered part {i}")
                actual = hashlib.sha256()
                with (directory / part).open("rb") as f:
                    for data in iter(lambda: f.read(BUF), b""):
                        actual.update(data)
                        full.update(data)
                        out.write(data)
                if actual.hexdigest() != expected:
                    raise ValueError(f"SHA-256 mismatch: {part}")
        if full.hexdigest() != digest:
            raise ValueError("Combined ISO SHA-256 mismatch")
        # Publish atomically without overwriting an existing file (NTFS/ext4).
        os.link(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    print(f"Verified: {output} ({digest})")


if __name__ == "__main__":
    try:
        join(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
    except (OSError, ValueError) as err:
        sys.exit(str(err))

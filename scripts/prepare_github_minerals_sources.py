"""Prepare reviewed public releases in a new directory; never install at runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = args.destination
    root.mkdir(parents=True, exist_ok=False)
    packages = {"spectral": "0.25", "pyrolite": "0.3.8.post1", "mplstereonet": "0.6.3",
                "periodictable": None, "mpltern": None, "sympy": "1.14.0", "mpmath": "1.3.0"}
    manifest = []
    for package, version in packages.items():
        endpoint = f"https://pypi.org/pypi/{package}/" + (f"{version}/json" if version else "json")
        with urllib.request.urlopen(endpoint, timeout=40) as response:
            meta = json.load(response)
        candidates = sorted(meta["urls"], key=lambda item: (not item["filename"].endswith(".whl"), item["filename"]))
        item = next(item for item in candidates if item["filename"].endswith(("none-any.whl", ".tar.gz")))
        with urllib.request.urlopen(item["url"], timeout=60) as response:
            data = response.read()
        digest = hashlib.sha256(data).hexdigest()
        if digest != item["digests"]["sha256"]:
            raise ValueError("Distribution SHA-256 mismatch: " + package)
        target = root / item["filename"]
        target.write_bytes(data)
        manifest.append({"package": package, "version": meta["info"]["version"], "file": target.name,
                         "url": item["url"], "sha256": digest, "requires": meta["info"].get("requires_dist")})
        # Inspect archive members without executing setup scripts or extracting links.
        if package in {"spectral", "pyrolite", "mplstereonet"}:
            out = root / "review" / package
            out.mkdir(parents=True)
            if target.suffix == ".whl":
                archive = zipfile.ZipFile(target)
                entries = [(name, lambda n=name: archive.read(n)) for name in archive.namelist() if not name.endswith("/")]
            else:
                archive = tarfile.open(target)
                entries = [(member.name, lambda m=member: archive.extractfile(m).read()) for member in archive.getmembers() if member.isfile()]
            wanted = ("algorithms.py", "continuum.py", "stereonet_math.py", "analysis.py", "codata.py", "transform.py", "norm.py", "setup.py", "pyproject.toml", "LICENSE", "LICENSE.txt", "LICENSE.rst", "COPYING")
            for name, read in entries:
                leaf = name.rsplit("/", 1)[-1]
                if leaf in wanted:
                    dest = out / name.replace("/", "__")
                    raw = read()
                    dest.write_bytes(raw)
                    print(json.dumps({"source": name, "review_file": str(dest), "sha256": hashlib.sha256(raw).hexdigest()}))
            archive.close()
    (root / "downloads.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"downloads": [{"package": row["package"], "version": row["version"]} for row in manifest], "root": str(root)}))


if __name__ == "__main__":
    main()

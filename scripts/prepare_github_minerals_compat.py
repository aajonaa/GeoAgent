"""Resolve only missing pure-Python dependencies against the captured CPU base."""
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

SOURCE = Path(r"C:\Users\jona\github\minerals-intake-20261024")
OUT = Path(r"C:\Users\jona\github\minerals-intake-20261025-r3")
OUT.mkdir(exist_ok=False)
base = json.loads((SOURCE / "base-versions.json").read_text())
rows = [r for r in json.loads((SOURCE / "downloads.json").read_text()) if r["package"] != "pyrolite"]
for row in rows:
    shutil.copyfile(SOURCE / row["file"], OUT / row["file"])
resolved = {canonicalize_name(r["package"]): r["version"] for r in rows}
queue = [Requirement("pyrolite==0.3.7"), Requirement("numpydoc==1.9.0"), Requirement("tinydb==4.8.2"), Requirement("Sphinx==8.2.3"), Requirement("docutils==0.21.2")]
preferred = {canonicalize_name(r.name): str(r.specifier).removeprefix("==") for r in queue}
environment = {"python_version": "3.12", "python_full_version": "3.12.11", "sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64", "implementation_name": "cpython", "extra": ""}
while queue:
    requirement = queue.pop(0)
    if requirement.marker and not requirement.marker.evaluate(environment):
        continue
    name = canonicalize_name(requirement.name)
    existing = resolved.get(name) or (None if name in preferred else base.get(name))
    if existing:
        if existing not in requirement.specifier:
            raise RuntimeError(f"Protected dependency conflict: {name} {existing} vs {requirement}")
        continue
    version = preferred.get(name)
    url = f"https://pypi.org/pypi/{name}/" + (f"{version}/json" if version else "json")
    with urllib.request.urlopen(url, timeout=40) as response:
        meta = json.load(response)
    if meta['info'].get('requires_python') and '3.12.11' not in SpecifierSet(meta['info']['requires_python']):
        raise RuntimeError("Requires incompatible Python: " + name)
    item = next(i for i in meta["urls"] if i["filename"].endswith("none-any.whl"))
    previous = Path(r"C:\Users\jona\github\minerals-intake-20261025-r2") / item["filename"]
    if previous.is_file():
        data = previous.read_bytes()
    else:
        with urllib.request.urlopen(item["url"], timeout=60) as response:
            data = response.read()
    sha = hashlib.sha256(data).hexdigest()
    if sha != item["digests"]["sha256"]:
        raise RuntimeError("Invalid hash: " + name)
    (OUT / item["filename"]).write_bytes(data)
    version = meta["info"]["version"]
    if version not in requirement.specifier:
        raise RuntimeError("Resolved version outside requested range: " + name)
    resolved[name] = version
    reqs = meta["info"].get("requires_dist") or []
    rows.append({"package": name, "version": version, "file": item["filename"], "url": item["url"], "sha256": sha, "requires": reqs})
    (OUT / "downloads-progress.json").write_text(json.dumps(rows, indent=2) + "\n")
    queue.extend(Requirement(r) for r in reqs)
    print(name + "==" + version, flush=True)
(OUT / "downloads.json").write_text(json.dumps(rows, indent=2) + "\n")
print("Ready: " + str(OUT), flush=True)

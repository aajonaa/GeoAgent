"""Update only the new intake's dependency binding, preserving the 220-tool base."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DOWNLOADS = Path(r"C:\Users\jona\github\minerals-intake-20261025-r3")
DELIVERY = ROOT / "catalog/source_delivery/github-minerals"
rows = json.loads((DOWNLOADS / "downloads.json").read_text())
pins = ["numpy==2.1.3", "scipy==1.15.3", "pandas==2.3.0", "matplotlib==3.10.7", "rasterio==1.4.3"]
pins += [r["package"] + "==" + r["version"] for r in rows]
registry_path = ROOT / "catalog/registry.json"
catalog = json.loads(registry_path.read_text(encoding="utf-8"))
for spec in catalog["tools"]:
    if spec.get("category") != "github_minerals":
        continue
    upstream = spec["metadata"]["upstream"]
    upstream["requirements"] = pins
    if upstream["package"] == "pyrolite":
        upstream["version"] = "0.3.7"
        spec["registration_metadata"]["source_commit"] = "ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca"
registry_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lock_path = DELIVERY / "upstream-lock.json"
lock = json.loads(lock_path.read_text())
lock["repositories"]["pyrolite"].update(version="0.3.7", commit="ab651b448ecd2ce1bc22d752b80a977a1f4dd1ca")
lock["distributions"] = rows
lock["scientific_dependencies"] = pins
lock["rejected_release"] = {"package": "pyrolite", "version": "0.3.8.post1", "reason": "Import references nonexistent matplotlib.colors.Norm", "evidence": "/data/wangjian/github-minerals-20261025-r1/import.log"}
lock_path.write_text(json.dumps(lock, indent=2) + "\n")
(ROOT / "requirements-github-minerals.txt").write_text("# Reviewed CPU profile; existing dependency versions remain protected.\n" + "\n".join(pins) + "\n")
row = next(r for r in rows if r["package"] == "pyrolite")
wheel = DOWNLOADS / row["file"]
if hashlib.sha256(wheel.read_bytes()).hexdigest() != row["sha256"]:
    raise ValueError("Release bytes changed")
with zipfile.ZipFile(wheel) as archive:
    names = [n for n in archive.namelist() if n.rsplit('/',1)[-1] in ('LICENSE', 'LICENSE.txt')]
    if len(names) != 1:
        raise ValueError("Ambiguous license in replacement release")
    (DELIVERY / "licenses/pyrolite.txt").write_bytes(archive.read(names[0]))
print(json.dumps({"pyrolite": "0.3.7", "pinned_dependencies": len(pins), "tools": len(catalog['tools'])}))

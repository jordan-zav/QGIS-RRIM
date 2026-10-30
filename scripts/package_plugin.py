"""Build a whitelisted QGIS plugin ZIP without profiles, caches or test data."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--extract-to", type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
metadata = configparser.ConfigParser(interpolation=None)
metadata.read(root / "metadata.txt", encoding="utf-8")
version = metadata["general"]["version"]
files = ["__init__.py", "qgis_rrim.py", "rrim_provider.py", "rrim_algorithm.py",
         "rrim_openness.py", "rrim_raster.py", "rrim_rgb_composer.py", "metadata.txt",
         "icon.png", "LICENSE", "README.md", "README.es.md",
         "docs/CODE_REVIEW_20261029.md", "docs/LIDAR_VALIDATION_1_1_0.md",
         "docs/images/lidar_comparison.png", "docs/images/lidar_detail.png"]
args.output.mkdir(parents=True, exist_ok=True)
archive = args.output / f"qgis_rrim_{version}.zip"
manifest = {}
with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as stream:
    for name in files:
        data = (root / name).read_bytes()
        if name.endswith(".py"):
            compile(data, name, "exec")
        stream.writestr("QGIS_RRIM/" + name, data)
        manifest[name] = hashlib.sha256(data).hexdigest()
with zipfile.ZipFile(archive) as stream:
    assert stream.testzip() is None
    assert len(stream.namelist()) == len(files)
    for name in files:
        assert stream.read("QGIS_RRIM/" + name) == (root / name).read_bytes()
    assert not args.extract_to.exists(), "Use a new extraction directory"
    stream.extractall(args.extract_to)
checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
(args.output / (archive.name + ".sha256")).write_text(
    checksum + "  " + archive.name + "\n", encoding="ascii")
(args.output / "package_manifest.json").write_text(
    json.dumps({"version": version, "sha256": checksum, "files": manifest}, indent=2), encoding="utf-8")
print(json.dumps({"archive": str(archive), "sha256": checksum, "file_count": len(files)}, indent=2))

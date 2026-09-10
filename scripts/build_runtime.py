"""Build application-only release artifacts without installing dependencies."""

import argparse
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

BOOTSTRAP = """import pathlib, subprocess, sys, tempfile, zipfile
if sys.version_info < (3, 12):
    sys.exit("Python 3.12+ required; Python is not bundled.")
with tempfile.TemporaryDirectory(prefix="legislativ-runtime-") as directory:
    with zipfile.ZipFile(pathlib.Path(sys.argv[0]).resolve()) as archive:
        archive.extractall(directory)
    try:
        result = subprocess.call([sys.executable, "-B", "-m", "scripts.launcher",
                                  *sys.argv[1:]], cwd=directory)
    except KeyboardInterrupt:
        result = 130
    sys.exit(result)
"""


def build(source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        with zipfile.ZipFile(
            stage / "legislativ.pyz", "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr("__main__.py", BOOTSTRAP)
            paths = list((source / "scripts").glob("*.py"))
            paths += [
                p
                for p in (source / "app").rglob("*")
                if p.is_file()
                and p.suffix
                in {
                    ".html",
                    ".css",
                    ".js",
                    ".mjs",
                    ".json",
                    ".woff2",
                    ".wasm",
                    ".pagefind",
                    ".svg",
                    ".png",
                    ".ico",
                    ".md",
                    ".jpg",
                    ".jpeg",
                    ".webp",
                    ".avif",
                }
            ]
            paths += list((source / "app").rglob("VERSIUNE"))
            for path in sorted(paths):
                if not path.is_symlink():
                    archive.write(path, path.relative_to(source).as_posix())
        for name in ("ruleaza.sh", "ruleaza.cmd"):
            shutil.copy2(source / name, stage / name)
        shutil.copy2(source / "docs" / "local-launch.md", stage / "README.md")
        bundle = output / "legislativ-local.zip"
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.iterdir()):
                archive.write(path, path.name)
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        (output / "SHA256SUMS").write_text(f"{digest}  {bundle.name}\n", encoding="ascii")
        return bundle


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("dist/runtime"))
    args = parser.parse_args()
    print(build(Path(__file__).resolve().parents[1], args.output))

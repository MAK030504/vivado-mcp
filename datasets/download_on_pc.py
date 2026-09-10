#!/usr/bin/env python3
"""Download FYP burn datasets onto your local PC (Windows/macOS/Linux).

Usage:
  pip install huggingface_hub roboflow
  set ROBOFLOW_API_KEY=your_key          # Windows cmd
  # export ROBOFLOW_API_KEY=your_key     # macOS/Linux
  python download_on_pc.py

Optional:
  set SKIP_MASS_HUMAN_BURNS=1
  set OUT_DIR=D:\\burn-datasets
"""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlretrieve


ROOT = Path(__file__).resolve().parent
OUT = Path(os.environ.get("OUT_DIR", ROOT / "downloads")).resolve()
SKIP_MASS = os.environ.get("SKIP_MASS_HUMAN_BURNS") == "1"


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  GET {url}\n    -> {dest}")
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    # urlretrieve doesn't take headers easily; use opener
    import urllib.request

    with urllib.request.urlopen(req, timeout=600) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)


def unzip(zip_path: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(dest)


def run(cmd: list[str]) -> None:
    print(" ", " ".join(cmd))
    subprocess.check_call(cmd)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("Downloading into:", OUT)

    # Kaggle Skin Burn
    kb = OUT / "kaggle-skin-burn"
    if not (kb / "extracted").exists():
        print("==> Kaggle Skin Burn Dataset")
        z = kb / "skin-burn-dataset.zip"
        download(
            "https://www.kaggle.com/api/v1/datasets/download/shubhambaid/skin-burn-dataset",
            z,
        )
        unzip(z, kb / "extracted")
    else:
        print("==> Kaggle Skin Burn already present")

    # last-databurn
    lb = OUT / "kaggle-last-databurn"
    if not (lb / "extracted").exists():
        print("==> Kaggle last-databurn")
        z = lb / "last-databurn.zip"
        download(
            "https://www.kaggle.com/api/v1/datasets/download/faresabbasai2022/last-databurn",
            z,
        )
        unzip(z, lb / "extracted")
    else:
        print("==> last-databurn already present")

    # Human skin burns (~800MB)
    hb = OUT / "kaggle-human-skin-burns"
    if not (hb / "extracted").exists():
        print("==> Kaggle Human Skin Burns (~800MB)")
        z = hb / "human-skin-burns.zip"
        download(
            "https://www.kaggle.com/api/v1/datasets/download/brendarangelolvera/human-skin-burns",
            z,
        )
        unzip(z, hb / "extracted")
    else:
        print("==> Human Skin Burns already present")

    # Hugging Face
    print("==> Hugging Face")
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install: pip install huggingface_hub")
        sys.exit(1)
    hf = OUT / "huggingface"
    repos = ["HLSS/HSR_Burns", "HLSS/SAM_Preprocessed_MHB"]
    if not SKIP_MASS:
        repos.insert(0, "HLSS/MassHumanBurns")
    else:
        print("  Skipping MassHumanBurns")
    for repo in repos:
        dest = hf / repo.split("/")[-1]
        print(f"  {repo} -> {dest}")
        snapshot_download(repo_id=repo, repo_type="dataset", local_dir=str(dest))

    # FUSeg
    print("==> FUSeg")
    fuseg = OUT / "fuseg" / "wound-segmentation"
    if not (fuseg / ".git").exists():
        fuseg.parent.mkdir(parents=True, exist_ok=True)
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/uwm-bigdata/wound-segmentation.git",
                str(fuseg),
            ]
        )

    # EBIS + samples
    print("==> EBIS materials + samples")
    misc = OUT / "misc"
    misc.mkdir(parents=True, exist_ok=True)
    if not (misc / "EBIS" / ".git").exists():
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/VEDAs-Lab/EBIS.git",
                str(misc / "EBIS"),
            ]
        )

    # Roboflow
    key = os.environ.get("ROBOFLOW_API_KEY", "").strip()
    if not key:
        print("==> Roboflow skipped (set ROBOFLOW_API_KEY to download)")
        print("    Free key: https://app.roboflow.com → Account → API Keys")
    else:
        print("==> Roboflow Universe")
        try:
            from roboflow import Roboflow
        except ImportError:
            print("Install: pip install roboflow")
            sys.exit(1)
        rf = Roboflow(api_key=key)
        out_rf = OUT / "roboflow"
        out_rf.mkdir(parents=True, exist_ok=True)
        jobs = [
            ("aibuildersclub", "skin-burns-4yoo2", "yolov8", None),
            ("ishaan-konar-uniko", "skinburns-xjtt6", "yolov8", None),
            ("burndegree", "pfa-hfzdi", "yolov8", None),
            ("burndegree", "pfa-hfzdi", "coco-segmentation", "pfa-hfzdi-coco-seg"),
        ]
        for ws, proj, fmt, folder in jobs:
            print(f"  {ws}/{proj} [{fmt}]")
            try:
                project = rf.workspace(ws).project(proj)
                versions = sorted(
                    project.versions(),
                    key=lambda v: int(str(getattr(v, "version", 0))),
                    reverse=True,
                )
                version = versions[0]
                loc = out_rf / (folder or proj)
                version.download(fmt, location=str(loc))
                print("    OK ->", loc)
            except Exception as e:
                print("    FAIL:", e)

    print("\nDone. Datasets are in:", OUT)


if __name__ == "__main__":
    main()

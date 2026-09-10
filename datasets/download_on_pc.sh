#!/usr/bin/env bash
# Download FYP burn datasets onto your local PC.
# Usage:
#   export ROBOFLOW_API_KEY=xxxxx   # optional but recommended
#   SKIP_MASS_HUMAN_BURNS=1 bash download_on_pc.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${OUT_DIR:-$ROOT/downloads}"
mkdir -p "$OUT"
cd "$OUT"

need() { command -v "$1" >/dev/null 2>&1 || { echo "Please install: $1"; exit 1; }; }
need curl
need unzip
need python3

echo "Downloading into: $OUT"

echo "==> Kaggle Skin Burn Dataset (YOLO degrees)"
mkdir -p kaggle-skin-burn
if [[ ! -d kaggle-skin-burn/extracted ]]; then
  curl -L --fail -A "Mozilla/5.0" \
    "https://www.kaggle.com/api/v1/datasets/download/shubhambaid/skin-burn-dataset" \
    -o kaggle-skin-burn/skin-burn-dataset.zip
  unzip -qo kaggle-skin-burn/skin-burn-dataset.zip -d kaggle-skin-burn/extracted
fi

echo "==> Kaggle last-databurn (1st/2nd/3rd folders)"
mkdir -p kaggle-last-databurn
if [[ ! -d kaggle-last-databurn/extracted ]]; then
  curl -L --fail -A "Mozilla/5.0" \
    "https://www.kaggle.com/api/v1/datasets/download/faresabbasai2022/last-databurn" \
    -o kaggle-last-databurn/last-databurn.zip
  unzip -qo kaggle-last-databurn/last-databurn.zip -d kaggle-last-databurn/extracted
fi

echo "==> Kaggle Human Skin Burns (~800MB hospital patches)"
mkdir -p kaggle-human-skin-burns
if [[ ! -d kaggle-human-skin-burns/extracted ]]; then
  curl -L --fail -A "Mozilla/5.0" \
    "https://www.kaggle.com/api/v1/datasets/download/brendarangelolvera/human-skin-burns" \
    -o kaggle-human-skin-burns/human-skin-burns.zip
  unzip -qo kaggle-human-skin-burns/human-skin-burns.zip -d kaggle-human-skin-burns/extracted
fi

echo "==> Hugging Face datasets"
python3 - <<'PY'
import os
from pathlib import Path
out = Path(os.environ.get("OUT", ".")).resolve()
# OUT is set below via export
PY
export OUT
python3 - <<PY
from pathlib import Path
from huggingface_hub import snapshot_download
import os
out = Path(r"$OUT") / "huggingface"
out.mkdir(parents=True, exist_ok=True)
repos = ["HLSS/HSR_Burns", "HLSS/SAM_Preprocessed_MHB"]
if os.environ.get("SKIP_MASS_HUMAN_BURNS") != "1":
    repos.insert(0, "HLSS/MassHumanBurns")
else:
    print("Skipping MassHumanBurns (large)")
for repo in repos:
    dest = out / repo.split("/")[-1]
    print(" ", repo, "->", dest)
    snapshot_download(repo_id=repo, repo_type="dataset", local_dir=str(dest))
PY

echo "==> FUSeg wound segmentation (method transfer)"
mkdir -p fuseg
if [[ ! -d fuseg/wound-segmentation/.git ]]; then
  git clone --depth 1 https://github.com/uwm-bigdata/wound-segmentation.git fuseg/wound-segmentation
fi

echo "==> EBIS access PDF + Michael-OvO samples"
mkdir -p misc
[[ -d misc/EBIS/.git ]] || git clone --depth 1 https://github.com/VEDAs-Lab/EBIS.git misc/EBIS
if [[ ! -d misc/Burn-Detection-Classification/.git ]]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/Michael-OvO/Burn-Detection-Classification.git misc/Burn-Detection-Classification
  (cd misc/Burn-Detection-Classification && git sparse-checkout set inference)
fi

echo "==> Roboflow Universe"
if [[ -z "${ROBOFLOW_API_KEY:-}" ]]; then
  echo "ROBOFLOW_API_KEY not set — skipping Roboflow."
  echo "Get a free key at https://app.roboflow.com → Account → API Keys"
  echo "Then: export ROBOFLOW_API_KEY=... && bash download_on_pc.sh"
else
  python3 - <<PY
import os
from pathlib import Path
from roboflow import Roboflow

out = Path(r"$OUT") / "roboflow"
out.mkdir(parents=True, exist_ok=True)
rf = Roboflow(api_key=os.environ["ROBOFLOW_API_KEY"])
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
        versions = sorted(project.versions(), key=lambda v: int(str(getattr(v, "version", 0))), reverse=True)
        version = versions[0]
        loc = out / (folder or proj)
        version.download(fmt, location=str(loc))
        print("    OK ->", loc)
    except Exception as e:
        print("    FAIL:", e)
PY
fi

echo
echo "Done. Datasets are in: $OUT"
du -sh "$OUT"/* 2>/dev/null | sort -h || true

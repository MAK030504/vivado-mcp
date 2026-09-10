#!/usr/bin/env bash
# Re-download publicly reachable burn/wound datasets into /workspace/datasets
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
mkdir -p kaggle-skin-burn kaggle-human-skin-burns huggingface fuseg misc roboflow

need_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "Missing: $1"; exit 1; }; }
need_cmd curl
need_cmd unzip
need_cmd git
need_cmd python3

echo "==> Kaggle Skin Burn Dataset"
if [[ ! -d kaggle-skin-burn/extracted ]] || [[ -z "$(ls -A kaggle-skin-burn/extracted 2>/dev/null || true)" ]]; then
  curl -L --fail -A "Mozilla/5.0" \
    "https://www.kaggle.com/api/v1/datasets/download/shubhambaid/skin-burn-dataset" \
    -o kaggle-skin-burn/skin-burn-dataset.zip
  mkdir -p kaggle-skin-burn/extracted
  unzip -qo kaggle-skin-burn/skin-burn-dataset.zip -d kaggle-skin-burn/extracted
else
  echo "    already present"
fi

echo "==> Kaggle Human Skin Burns"
if [[ ! -d kaggle-human-skin-burns/extracted ]] || [[ -z "$(ls -A kaggle-human-skin-burns/extracted 2>/dev/null || true)" ]]; then
  curl -L --fail -A "Mozilla/5.0" \
    "https://www.kaggle.com/api/v1/datasets/download/brendarangelolvera/human-skin-burns" \
    -o kaggle-human-skin-burns/human-skin-burns.zip
  mkdir -p kaggle-human-skin-burns/extracted
  unzip -qo kaggle-human-skin-burns/human-skin-burns.zip -d kaggle-human-skin-burns/extracted
else
  echo "    already present"
fi

echo "==> Hugging Face synthetic / TBSA datasets"
python3 - <<'PY'
from huggingface_hub import snapshot_download
for repo in ["HLSS/MassHumanBurns", "HLSS/HSR_Burns", "HLSS/SAM_Preprocessed_MHB"]:
    out = f"/workspace/datasets/huggingface/{repo.split('/')[-1]}"
    print(" ", repo, "->", out)
    snapshot_download(repo_id=repo, repo_type="dataset", local_dir=out)
PY

echo "==> FUSeg / AZH wound segmentation repo"
if [[ ! -d fuseg/wound-segmentation/.git ]]; then
  git clone --depth 1 https://github.com/uwm-bigdata/wound-segmentation.git fuseg/wound-segmentation
else
  echo "    already cloned"
fi
AZH_ZIP="fuseg/wound-segmentation/data/wound_dataset/azh_wound_care_center_dataset_patches.zip"
if [[ -f "$AZH_ZIP" ]] && [[ ! -d fuseg/wound-segmentation/data/wound_dataset/azh_patches ]]; then
  unzip -qo "$AZH_ZIP" -d fuseg/wound-segmentation/data/wound_dataset/azh_patches
fi

echo "==> EBIS access materials + Michael-OvO samples"
[[ -d misc/EBIS/.git ]] || git clone --depth 1 https://github.com/VEDAs-Lab/EBIS.git misc/EBIS
if [[ ! -d misc/Burn-Detection-Classification/.git ]]; then
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/Michael-OvO/Burn-Detection-Classification.git misc/Burn-Detection-Classification
  (cd misc/Burn-Detection-Classification && git sparse-checkout set inference)
fi

if [[ "${1:-}" == "--roboflow" ]]; then
  if [[ -z "${ROBOFLOW_API_KEY:-}" ]]; then
    echo "ROBOFLOW_API_KEY not set; skipping Roboflow downloads"
    exit 1
  fi
  echo "==> Roboflow Universe burn datasets"
  python3 - <<'PY'
import os
from roboflow import Roboflow
rf = Roboflow(api_key=os.environ["ROBOFLOW_API_KEY"])
projects = [
    ("pelukbakar", "pb", 1),  # may need version check
    ("aibuildersclub", "skin-burns-4yoo2", 2),
    ("ishaan-konar-uniko", "skinburns-xjtt6", 3),
    ("onur-mutlu", "wound-skinburn-s1sjt", 1),
    ("burndegree", "pfa-hfzdi", 1),
]
out_root = "/workspace/datasets/roboflow"
os.makedirs(out_root, exist_ok=True)
for ws, proj, ver in projects:
    try:
        print(f"  {ws}/{proj} v{ver}")
        project = rf.workspace(ws).project(proj)
        # try requested version, else latest
        try:
            version = project.version(ver)
        except Exception:
            versions = project.versions()
            version = versions[0] if versions else None
        if version is None:
            print("    no versions")
            continue
        version.download("yolov8", location=f"{out_root}/{proj}")
    except Exception as e:
        print(f"    FAILED: {e}")
PY
else
  echo "==> Roboflow skipped (pass --roboflow with ROBOFLOW_API_KEY to enable)"
fi

echo
echo "Done. See $ROOT/README.md for inventory."
du -sh "$ROOT"/* 2>/dev/null | sort -h

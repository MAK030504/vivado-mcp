# Download burn datasets on your PC

You have two options.

---

## Option A — Fastest for what we already prepared (~343 MB)

In the **Cloud Agent** file browser, download these zips:

| File | Path on agent | Size |
|---|---|---|
| Roboflow burn sets | `datasets/pc-transfer/roboflow-burn-datasets.zip` | ~308 MB |
| Kaggle Skin Burn (YOLO) | `datasets/pc-transfer/kaggle-skin-burn.zip` | ~17 MB |
| Kaggle last-databurn (folders) | `datasets/pc-transfer/kaggle-last-databurn.zip` | ~18 MB |

Also mirrored under `/opt/cursor/artifacts/`.

Unzip on your PC into something like `C:\burn-datasets\` or `~/burn-datasets/`.

> The big Hugging Face set (**MassHumanBurns**, ~22–54 GB) is too large to zip-transfer. Use Option B for that.

---

## Option B — Re-download everything fresh on your PC (recommended for full set)

### 1. One-time setup

```bash
pip install huggingface_hub roboflow
```

Create a free [Roboflow](https://app.roboflow.com/) account → **Account → API Keys** → copy Private API Key.

### 2. Run the script

From this repo:

```bash
cd datasets
# Linux / macOS / Git Bash
export ROBOFLOW_API_KEY="YOUR_KEY_HERE"
bash download_on_pc.sh
```

Or with Python (Windows-friendly):

```bash
cd datasets
set ROBOFLOW_API_KEY=YOUR_KEY_HERE
python download_on_pc.py
```

### 3. What you get

```
burn-datasets/                 # created next to the script, or ./downloads/
  kaggle-skin-burn/
  kaggle-human-skin-burns/     # ~800 MB
  kaggle-last-databurn/
  roboflow/
    skin-burns-4yoo2/
    skinburns-xjtt6/
    pfa-hfzdi/
    pfa-hfzdi-coco-seg/
  huggingface/
    MassHumanBurns/            # large — optional flag
    HSR_Burns/
    SAM_Preprocessed_MHB/
  fuseg/
  misc/
```

Skip the huge synthetic set with:

```bash
SKIP_MASS_HUMAN_BURNS=1 bash download_on_pc.sh
```

---

## Manual browser links (no script)

- Kaggle Skin Burn: https://www.kaggle.com/datasets/shubhambaid/skin-burn-dataset  
- Human Skin Burns: https://www.kaggle.com/datasets/brendarangelolvera/human-skin-burns  
- last-databurn: https://www.kaggle.com/datasets/faresabbasai2022/last-databurn  
- Roboflow Skin Burns: https://universe.roboflow.com/aibuildersclub/skin-burns-4yoo2 → Download Dataset  
- Roboflow SkinBurns: https://universe.roboflow.com/ishaan-konar-uniko/skinburns-xjtt6  
- Roboflow PFA: https://universe.roboflow.com/burndegree/pfa-hfzdi  
- HF MassHumanBurns: https://huggingface.co/datasets/HLSS/MassHumanBurns  
- FUSeg: https://github.com/uwm-bigdata/wound-segmentation  

---

## Notes

- Prefer **`skin-burns-4yoo2`** and **`pfa-hfzdi`** for cleaner labels.
- `skinburns-xjtt6` is large but its `data.yaml` class names look messy — inspect before training.
- Do **not** commit Roboflow API keys to git.

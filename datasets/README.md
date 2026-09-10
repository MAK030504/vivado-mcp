# Burn Wound Datasets Inventory

Downloaded for FYP exploration: severity classification, segmentation, TBSA estimation, and wound-healing method transfer.

**Location:** `/workspace/datasets`  
**Last updated:** 2026-09-10

> Large binary archives are **not** committed to git (see `.gitignore`). They live on this machine under `datasets/`. Re-run `./download_all.sh` to refresh.

---

## Downloaded successfully

### 1. Kaggle Skin Burn Dataset (primary degree labels)
| | |
|---|---|
| **Path** | `kaggle-skin-burn/extracted/` |
| **Source** | https://www.kaggle.com/datasets/shubhambaid/skin-burn-dataset |
| **Size** | ~17 MB zip → ~1.2k images + YOLO labels |
| **Labels** | YOLO classes `0/1/2` = 1st / 2nd / 3rd degree |
| **Stats** | Images: 1227 · Label files: 1441 · Boxes: class0=998, class1=1212, class2=408 |
| **Use for** | Burn depth/severity detection & benchmarking |
| **Caveat** | Web-scraped; **not** clinician-verified |

### 2. Human Skin Burns (hospital patches)
| | |
|---|---|
| **Path** | `kaggle-human-skin-burns/extracted/` |
| **Source** | https://www.kaggle.com/datasets/brendarangelolvera/human-skin-burns |
| **Size** | ~792 MB zip → ~833 MB extracted (~2.8k files) |
| **Labels** | Mostly unlabeled burn patches + `healthy` / `background` folders (batch folders `burns1-100` … `burns1001-1100`) |
| **Use for** | Extra clinical-looking burn texture; may need doctor labeling for degree |
| **Caveat** | No structured 1st/2nd/3rd degree folders |

### 3. Hugging Face — MassHumanBurns (synthetic TBSA)
| | |
|---|---|
| **Path** | `huggingface/MassHumanBurns/` |
| **Source** | https://huggingface.co/datasets/HLSS/MassHumanBurns |
| **Contents** | `images.7z` (~22 GB), `burn_masks.7z`, `full_masks.7z`, `labels.npy`, `gender.json` |
| **Extracted** | Masks extracted under `*_extracted/`; images archive may still be extracting |
| **Use for** | TBSA / burned-area estimation (synthetic bodies, not real wounds) |

### 4. Hugging Face — HSR_Burns (TBSA validation)
| | |
|---|---|
| **Path** | `huggingface/HSR_Burns/` |
| **Source** | https://huggingface.co/datasets/HLSS/HSR_Burns |
| **Contents** | 4 human models × 30 images (front/back burn patterns) |
| **Use for** | Small TBSA validation set |

### 5. Hugging Face — SAM_Preprocessed_MHB
| | |
|---|---|
| **Path** | `huggingface/SAM_Preprocessed_MHB/` |
| **Source** | https://huggingface.co/datasets/HLSS/SAM_Preprocessed_MHB |
| **Contents** | SAM2-refined burn/full masks (extracted) |
| **Use for** | Mask-quality / TBSA preprocessing experiments |

### 6. FUSeg + AZH + Medetec (chronic wound segmentation — method transfer)
| | |
|---|---|
| **Path** | `fuseg/wound-segmentation/data/` |
| **Source** | https://github.com/uwm-bigdata/wound-segmentation |
| **Contents** | Foot Ulcer Segmentation Challenge (~2.2k files), Medetec foot ulcer 224, AZH patches (unzipped) |
| **Use for** | Segmentation / longitudinal-method ideas (**ulcers, not burns**) |
| **Ethics note** | AZH/FUSeg: de-identified clinical wound images with specialist annotations |

### 7. Michael-OvO inference samples
| | |
|---|---|
| **Path** | `misc/Burn-Detection-Classification/inference/` |
| **Source** | https://github.com/Michael-OvO/Burn-Detection-Classification |
| **Contents** | 6 labeled sample images (1st/2nd/3rd degree) |
| **Use for** | Quick smoke tests; private training set is **not** released |

### 8. EBIS access materials (dataset itself gated)
| | |
|---|---|
| **Path** | `misc/EBIS/` |
| **Source** | https://github.com/VEDAs-Lab/EBIS |
| **Contents** | README + `commitments/Commitment_EBIS-Dataset.pdf` |
| **Action** | Sign PDF → email **vedas.cs@gmail.com** for ~600 expert-consulted burn/non-burn masks |

---

## Could not download (need credentials / approval)

| Dataset | Why blocked | What to do |
|---|---|---|
| **Roboflow** PB / SkinBurns / wound+skinburn / AiBuildersClub / PFA | API key required (401/403) | Create free Roboflow account → set `ROBOFLOW_API_KEY` → re-run `./download_all.sh` |
| **EBIS full images** | Signed commitment | Email after signing PDF in `misc/EBIS/commitments/` |
| **IIT Roorkee / AIIMS Rishikesh (803 clinical)** | SPA site; no open zip found | https://geninfo.iitr.ac.in/projects — download via their portal / contact authors |
| **Alberta 1684 surgeon-labeled** | Not public | Email BAM paper authors |
| **Queen Astrid RGB+LDI (570 pairs)** | Not public | Email paper authors |
| **Zenodo “Skin Burn Dataset”** | Only a PDF placeholder, not images | Use Kaggle copy instead (already downloaded) |
| **Longitudinal same-wound burn series** | Does not exist publicly | Collect at Burns Center |

---

## Suggested FYP mapping

| Module | Start with |
|---|---|
| Severity / depth detection | `kaggle-skin-burn` (+ later doctor-validated subset) |
| Burn region segmentation | Request EBIS; meanwhile FUSeg for pipeline practice |
| TBSA / area | `MassHumanBurns` + `HSR_Burns` |
| Recovery monitoring | **Local Burns Center longitudinal collection only** |
| Extra clinical texture | `kaggle-human-skin-burns` (needs labeling) |

---

## Re-download / refresh

```bash
cd /workspace/datasets
./download_all.sh
# Optional Roboflow (after exporting a free API key):
# export ROBOFLOW_API_KEY=xxxxx
# ./download_all.sh --roboflow
```

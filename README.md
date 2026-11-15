# CellIQ: Smarter Review. Better Care.

A lung scan **triage support** website for doctors. A radiologist uploads a scan for a patient. CellIQ returns an AI result,
a priority level (routine, priority review, high priority) and a picture of where the AI looked. A doctor reviews it, adds notes
and approves a report that can be downloaded as a PDF or emailed. Every action is written to an activity log.

> **Research prototype. Not a diagnostic tool and not medical advice.** All patients are fake demo records.
> Never enter real patient data. Built for the Veritas AI Hackathon 2026 (Health track).

Team: Chinmayi Samant, Daksh Patil and Rajvi Yadav. The full write-up is in [`docs/CellIQ_writeup.docx`](docs/CellIQ_writeup.docx).

## What is in it

**Tissue model (our own).** EfficientNet-B0 trained on the lung part of the public LC25000 dataset. It sorts a stained slide into
adenocarcinoma, squamous cell carcinoma or normal lung, and a Grad-CAM heatmap shows where it looked. Weights, metrics and
evaluation images are in `models/tissue_v2/`. Training notebooks are in `ml/`.

**CT detector (open source, wired into the site).** The MONAI `lung_nodule_ct_detection` bundle (3D RetinaNet, Apache-2.0)
runs on a whole CT volume a radiologist uploads and marks nodule *candidates* with boxes and scores. It does not say whether a
nodule is cancer. Its 160 MB weights are not in this repo; see [`models/ct_detector/README.md`](models/ct_detector/README.md).
Saved example results on 4 public scans are in `demo_ct/` and display without the weights.

**Website (`web/`, plain JavaScript) and API (`api/`, FastAPI + SQLite).** Login with roles, dashboard, patient profiles,
scan upload, heatmap and CT slice viewer, doctor review, notes, reports (template text; optional Gemini drafting), activity
log and a model performance page. 34 automated tests are in `tests/`.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env          # set CELLIQ_JWT_SECRET (see the file for how)
python -m api.seed            # creates fake demo users and patients (logins are listed in api/seed.py)
uvicorn api.main:app --port 8000
```

Open http://localhost:8000/app/ for the website and http://localhost:8000/docs for the API docs.
The demo logins in `api/seed.py` are fake and for local testing only.

Tests: `python -m pytest -q`

CT analysis (optional): `pip install "monai[all]" SimpleITK` and install the weights as described in `models/ct_detector/README.md`.
On a PC without a GPU a full CT takes roughly 25 to 60 minutes.

## What we measured

| Test | Result |
|---|---|
| Tissue model, held-out LC25000 test set (1,711 images) | 99.59% correct; 99.36% with colour removed |
| CT detector, 24 then 40 public LUNA16 scans | about 78% and 73% of marked nodules found at 1 false alarm per scan (wide ranges) |
| CT detector, 4 random LUNA16 scans through the site | 3 of 4 marked nodules located; the 4th was about 4 mm outside the strict rule; 3 extra flagged spots are not on the reference list |
| Tissue model, 7 public images from other labs | mostly wrong |

Details and every failed attempt are in [`docs/PROJECT_LOG.md`](docs/PROJECT_LOG.md).

## Limitations

- The tissue model does not hold up on slides from other labs (different stains and magnifications). On 7 outside images it
  called normal lung squamous cell carcinoma and mixed up cancer types. Its 99% applies to its own dataset only.
- The CT score is not a cancer probability. Small nodules can be missed, and some high-scoring spots are not on the
  reference list, so we cannot tell whether they are false alarms. A single CT image cannot be analysed, only a full 3D volume.
- Four CT scans and seven outside tissue images are far too few for accuracy claims.
- Public data only, fake patients, no clinician validation. Not for any medical use.

## Credits

- LC25000 lung and colon histopathology images: https://www.kaggle.com/datasets/andrewmvd/lung-and-colon-cancer-histopathological-images (paper: https://arxiv.org/abs/1912.12142)
- MONAI lung_nodule_ct_detection (Apache-2.0): https://github.com/Project-MONAI/model-zoo/tree/dev/models/lung_nodule_ct_detection
- LUNA16 (CC BY 4.0): https://luna16.grand-challenge.org/ , built from LIDC-IDRI (CC BY 3.0): https://www.cancerimagingarchive.net/collection/lidc-idri/
- Wikimedia Commons histology images (CC licences): https://commons.wikimedia.org
- EfficientNet: https://arxiv.org/abs/1905.11946 · Grad-CAM: https://arxiv.org/abs/1610.02391
- PyTorch, FastAPI, SQLAlchemy, SimpleITK
- AI tool: Claude (Anthropic), used as a coding assistant

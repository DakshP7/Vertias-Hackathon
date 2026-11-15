# CellIQ Project Log

Record of what was built, the errors fixed, and the strengths and weaknesses found.
Research and educational prototype. Not for real diagnosis. All patients are fake demo records.

Last updated: 2026-11-13

---

## 1. Project in one paragraph

CellIQ is a lung scan triage support platform for the Veritas AI Hackathon (Healthcare track). Radiologists upload a
chest CT or a tissue image into a patient profile. An AI model returns a risk score, a priority label and a Grad-CAM
heatmap. Any doctor can open the file, review the AI result, add notes, generate a Gemini patient report, approve it,
and email it. The AI supports the doctor and never diagnoses.

## 2. Key decisions

| Decision | Detail |
|---|---|
| Lung only | Breast was dropped. Pitch, docs and code are lung only |
| Two models | CT model (train on IQ-OTH/NCCD) and tissue model (train on LC25000 lung folders). Never mixed in one model |
| External test | Kaggle Chest CT-Scan images, planned for the CT model, not done yet |
| Localization | v1 = classifier plus Grad-CAM. A true nodule detector (LUNA16) is a stretch goal |
| Access | Every doctor can see every patient. All views and changes go in the audit log |
| Reports | One doctor approves. Gemini gets structured findings only (no name, ID, contact, images). Template fallback if no key |
| Email | Outbox mode by default (saved as .eml, nothing sent). Real Gmail needs GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env |
| UI | Built-in dark UI (plain HTML/JS in web/), styled after a user-supplied design idea with CellIQ's own branding |
| Name | Team name is CellIQ (the spelling CellIQI was a typo) |

## 3. What exists

- `cellIQ/api/` FastAPI backend: auth and roles, patients, visits, scans, notes, doctor reviews, reports (draft, edit,
  approve, PDF, email), dashboard, audit log, model card and metrics endpoints.
- `cellIQ/web/` built-in UI: login, dashboard, patient directory, patient page, upload page, audit log, model card.
- `cellIQ/tests/` 25 automated tests, all passing at last run.
- `cellIQ/ml/CellIQ_lung_training.ipynb` copy of the base training notebook.
- AI inside the app is still a PLACEHOLDER (`api/services/ml_service.py`). Scores are a hash of the image bytes and
  mean nothing. Every result is labelled as such.
- Demo accounts: rad1 (radiologist), doc1 and doc2 (doctors), admin. Passwords are in `api/seed.py` (demo only).

## 4. Errors fixed

### App, backend and UI
| # | Problem | Fix |
|---|---|---|
| 1 | 12 tests failed: `PatientListItem` required a `status` field when validated from the database row | Gave `status` a default of "New" |
| 2 | Report findings crashed on a patient with `pack_years` = None | Used `(pack_years or 0)` |
| 3 | Doctor review list showed "[object HTMLDivElement]" | `replaceChildren` was given an array; spread it into arguments |
| 4 | Times showed in UTC but labelled as local (off by hours) | UI now treats server timestamps without a zone as UTC |
| 5 | Placeholder banner read "PLACEHOLDER RESULT. PLACEHOLDER result..." | Changed the prefix to "NOT A REAL RESULT." |
| 6 | Family-history checkbox in the patient dialog had duplicated logic | Simplified to one checkbox |
| 7 | Logo subtitle styling hit the wrong elements | Used a `small` element and a dedicated CSS rule |
| 8 | Dashboard returned 404 / "Not Found" in the UI after backend changes | An old server was still holding port 8000. Stopped my own old process and restarted |
| 9 | Shell commands with inline heredocs failed with quoting errors | Moved patches into script files and ran those |

### Colab and ML
| # | Problem | Fix |
|---|---|---|
| 10 | Notebook was saved as `.txt`, so Colab showed raw text | Rename to `.ipynb` (a correctly named copy was made) |
| 11 | Step 3 FileNotFoundError: the Kaggle download cell was placed after Step 9, so the data folder did not exist yet | Run the download cell first, then a cell that finds the folder automatically, then Step 3 |
| 12 | The `os.walk` inspection cell used `files` as a loop variable and would overwrite the image list from Step 3 | Use `_` instead |
| 13 | First training run used 5 groups (colon and lung) because the folder held both | Filter to folders starting with `lung_`, retrain: 3 groups, 2,026 test images |
| 14 | A "99.8% accuracy" claim was about to be told to the team, but it was not in any result | Corrected. Use only measured results |
| 15 | The Kaggle dataset name for IQ-OTH/NCCD was given from memory and could not be confirmed | Use the snippet shown on the Kaggle page, or the official Mendeley zip with `ZIP_PATH` |

## 5. Results so far (tissue model, EfficientNet-B0)

| Run | Result |
|---|---|
| 5-group run (lung + colon), discarded | 99.9% accuracy on 3,376 test images, 4 errors (3 lung_aca called lung_scc, 1 lung_scc called lung_aca). Not valid for the app |
| Lung-only run (the real one) | Val accuracy 100% by epoch 2 of phase 2. Test: 100% on 2,026 images, every sensitivity and specificity 1.000, AUC 1.0, zero errors. The failure gallery was empty |
| Colour-removed check | Accuracy fell from 100% to **90.4%** when images were converted to grayscale |

### CT model (EfficientNet-B0, IQ-OTH/NCCD, 3 groups), trained 2026-11-13

- Training: val accuracy bounced between 0.73 and 0.83 (best val loss 0.438, final val acc 0.829), train acc reached 0.929.
- Test set is tiny: 180 images (20 benign, 90 malignant, 70 normal), split in blocks of neighbouring files.
- Test accuracy 0.872, macro F1 0.618, AUC (one-vs-rest) 0.86.
- Per group: Malignant 90/90 correct (sensitivity 1.000). Normal 67/70 (3 called benign). **Benign 0/20 correct: all 20
  were called normal** (sensitivity 0.000).
- 23 wrong predictions in total: 20 benign called normal, 3 normal called benign.
- Heatmaps mostly sit on the centre of the chest (heart and mediastinum), not on clear lesions. One malignant example
  highlighted a band on the image edge outside the body, a possible shortcut or artifact.
- The "colour removed" check is meaningless for CT: the images are already grayscale, so it just repeated the test
  accuracy (0.872).
- Weaknesses added: benign class is never detected (only ~120 benign images exist); perfect malignant score may be
  inflated by neighbouring slices from the same patient and by scanner or window differences between classes;
  the test set is too small for stable metrics.

### CT model v2: benign + normal merged into "Non-malignant" (malignant vs non-malignant), trained 2026-11-13

- Output folder: `/content/cellIQ_lung_ct_binary`. Split sizes 747 / 170 / 180. Val accuracy ended at 0.965.
- Test: 90/90 non-malignant and 90/90 malignant, 100% accuracy, zero errors. (Merging made the unseparable benign
  scans count as correct. It did not teach the model to tell benign from normal.)
- **Shortcut test: with the middle 60% of each image hidden (only the outer edges visible), test accuracy was still
  1.0.** The model can classify the CT test set from non-lung image borders alone, so the 100% score is NOT evidence
  that it recognises lung findings. It is probably using dataset artifacts (scanner, field of view, window settings or
  similar differences between classes).
- Consequence: do not present the CT model as cancer detection. Its score is not trustworthy until it is retrained
  with a centre crop (lungs only) and tested on an independent CT set.

### CT model v3: centre-crop retrain (folder `/content/cellIQ_lung_ct_centre`)

- Added CenterCrop(65%) then resize, in both train and eval transforms. Val accuracy 0.965, test 100% (180 images), zero errors.
- Still 100% after cropping, so the crop did not expose a lower honest score. The test set is small and may still share
  patients (neighbouring slices) and class-specific scanner traits inside the crop.
- The old edge-only check scored 0.911 on this model, but that test feeds full-size images to a model trained on crops,
  so it is not a like-for-like comparison.
- Heatmaps now cover the lungs and mediastinum more, but are still broad and sometimes spill outside the body.
- Conclusion: the CT result remains untrustworthy until it is checked on the independent Kaggle Chest CT-Scan set.

### External test of the CT centre-crop model (Kaggle Chest CT-Scan images, never trained on)

- 1,000 images: 215 non-malignant (normal), 785 malignant (all cancer types treated as malignant).
- At threshold 0.5: sensitivity 0.997, **specificity 0.093**, AUC 0.839.
- Meaning: it flagged almost everything as malignant (about 91% of normal scans were flagged). Always answering
  "malignant" would score 78.5% accuracy on this set, so the high sensitivity is not meaningful by itself.
- AUC 0.84 shows some ability to rank cancers above normals, but the 100% in-dataset score did NOT transfer.
  The 0.5 threshold does not work on data from another source (domain shift).
- Presentation line: "On independent CT data the model caught 99.7% of malignant scans but also flagged 91% of
  normal scans (AUC 0.84), so it is not ready for use."

### Decision (2026-11-13): train a combined CT model

- Chosen to fix the transfer problem: train on IQ-OTH/NCCD plus the Kaggle Chest CT-Scan set together, with each
  source and class equally weighted, and a threshold picked on validation data for at least 95% sensitivity.
- Held-out tests per source (IQ block-split test; Kaggle's own test folder). Trade-off: no fully independent test
  remains, so report per-source results and say so. Output folder planned: `/content/cellIQ_lung_ct_combined`.

### Combined CT model results (folder `/content/cellIQ_lung_ct_combined`)

- Training: val acc 0.971 at the end; threshold chosen on validation for >=95% sensitivity = 0.69 (validation had only
  13 Kaggle non-malignant images, so this is rough).
- Held-out tests: IQ-OTH/NCCD (180): sensitivity 1.000, specificity 1.000, AUC 1.000.
  Kaggle Chest CT test folder (315; 261 malignant, 54 normal): sensitivity 1.000, specificity 0.981, AUC 0.997.
- Caveat: this does NOT show better generalisation. Both sources were in training, so the model can learn each source's
  own artifacts. The earlier single-source model failed on the other source (specificity 0.093), and no third
  independent source has been tested. Kaggle's own train/test split may also share patients (unknown).
- Metrics and the threshold were saved to metrics.json and meta.json in the output folder.
- **Edges-only check on the combined model** (centre of the cropped image hidden): IQ-OTH/NCCD 0.978 (majority-guess
  baseline 0.50), Kaggle Chest CT 0.997 (baseline 0.829). Both far above baseline, so the model still classifies from
  the frame of the image, which strongly suggests it uses dataset artifacts (scanner, framing, body outline, table)
  and not lung findings. The near-perfect CT scores must not be presented as cancer detection.
- Decision: try a "robust" retrain (folder `/content/cellIQ_lung_ct_robust`): tighter centre crop (60%), random zoom
  crops, per-image intensity normalisation, strong brightness/contrast jitter, an elliptical mask hiding image corners,
  and random erasing, then repeat the edges-only check. Preprocessing must be copied exactly into the API for inference.
- **Robust CT model results** (`/content/cellIQ_lung_ct_robust`, threshold 0.47, val acc 0.959):
  IQ-OTH/NCCD test (180): sensitivity 0.978, specificity 1.000, AUC 1.000, edges-only accuracy 0.939 (baseline 0.50).
  Kaggle Chest CT test (315): sensitivity 0.973, specificity 0.926, AUC 0.994, edges-only accuracy 0.990 (baseline 0.829).
  The mitigations made training harder and the numbers slightly lower, but edges-only accuracy is still far above
  baseline, so the shortcut is NOT removed. Likely cause: acquisition differences confounded with class inside each
  dataset. No further training trick will fix that with these datasets. Use this model as the demo CT model and
  publish the edges-only numbers on the model card.
  Preprocessing for inference: resize 224, centre crop 60%, resize 224, ToTensor, per-image normalisation
  ((x-mean)/std clamp +-3, /6 + 0.5), ImageNet normalise, multiply by elliptical mask (0.95).
- **New direction (2026-11-14):** two-stage story. Stage 1 (CT screening): use an open-source nodule detector (MONAI lung
  nodule CT detection, trained on LUNA16) run in Colab on a few public CT volumes, shown in the app as precomputed
  results with boxes and a slice scroller, labelled as nodule candidates. Stage 2 (biopsy slides): keep our tissue
  model, retrained to be colour-robust and evaluated with a group-aware split (near-duplicate augmented copies kept in
  the same split) so the test score is honest. The CT classifiers become secondary demo models.
- **Tissue model v2 (run by Claude in the user's Colab on a T4, notebook `ml/CellIQ_tissue_v2.ipynb`):**
  near-duplicate grouping via pretrained embeddings (single-linkage chained unrelated photos at low thresholds, so the
  lowest threshold with biggest group <= 700 was used: similarity 0.90, 5,530 groups), StratifiedGroupKFold 7 folds
  (train 9,988 / val 1,802 / test 1,711, balanced per class), colour-robust augmentation (RandomGrayscale, saturation
  and hue jitter, random resized crops). Evidence of the old problem: in a RANDOM split 67.1% of test images had a
  near-identical twin (similarity >= 0.90) in train. In the group split that is 0% by construction, but 49.7% still
  have a lookalike at >= 0.85, so the score may still be optimistic.
  Results: val acc 0.998; test accuracy 0.9924 (n=1,711); with colour removed (grayscale) 0.9877 (v1 fell from 100% to
  90.4%, so colour dependence is much smaller); cancer-vs-normal (risk = 1 - P(lung_n)): sensitivity 0.997,
  specificity 1.0, AUC 1.0, threshold 0.99 (probabilities saturate, treat threshold with care).
  Output zip `/content/cellIQ_lung_slides_v2.zip` (17.2 MB) is still only in Colab until downloaded.
- **Tissue v2 connected to the app (2026-11-13):** zip downloaded from Colab (17.2 MB) and unpacked into `models/tissue_v2`.
  Confusion matrix on 1,711 test images: lung_aca 554 correct (1 called normal, 1 called scc); lung_n 563/563; lung_scc 581
  correct, 11 called aca (13 errors in total). Heatmaps now cluster on groups of cell nuclei (more plausible than v1).
  `ml_service.py` now runs real inference + Grad-CAM for tissue scans (risk = 1 - P(lung_n); tiers: high >= 0.90,
  review >= 0.50, a heuristic because probabilities saturate), rejects grayscale images as 'cannot assess', and keeps
  CT as a flagged placeholder. Model card and /metrics report the measured tissue results. 27 tests pass. Checked with
  three real slide crops: all three classified correctly (first request 8 s while loading, then 0.1 s).
- **CT nodule detector run (2026-11-13, in Colab under the Daksh Patil Google account the user chose to use, T4 GPU):**
  open-source MONAI `lung_nodule_ct_detection` bundle v0.6.9 (the bundle's own LICENSE file is Apache-2.0, copyright
  MONAI Consortium), run in raw LUNA16 mode on 4 scans from LUNA16 subset0 (3 with radiologist-marked nodules, 1
  without). Whole subset download was too slow (about 1.4 MB/s from Zenodo), so single scans were read from the remote
  zip with `remotezip` (31-155 MB each). Problems fixed along the way: missing `import json`; 4 data-loader workers
  were killed for lack of RAM (set to 0); the bundle does not create its output folder; and my coordinate conversion
  wrongly flipped x and y (the detector's boxes are already in LUNA16 world coordinates).
  Result with LUNA16's rule (detection centre within the marked nodule's radius): 5 of 8 marked nodules found at any
  score threshold; at score >= 0.9, 1.0 unmatched detection per scan (2.5 at >= 0.7). Per nodule: case 1 found 3/3
  (scores 1.000, 0.996, 1.000); case 2 found the 5.2 mm nodule (0.998) and nearly the 8.1 mm one (score 0.985, centre
  5.0 mm away vs 4.05 mm radius = strict miss); case 3 found the 6.0 mm nodule (1.000), missed the 4.3 mm one by 0.15 mm
  (score 0.256) and the 5.1 mm one (score 0.020). Only 4 scans, so the figures are very noisy. Subset0 is believed (not
  verified) to be the released model's validation fold. Credit: LUNA16 (CC BY 4.0) from LIDC-IDRI (CC BY 3.0).
  Export zip (10.8 MB: 256x256 lung-window JPEG slices per case, meta.json with detections and radiologist nodules,
  summary.json) was downloaded and unpacked into `demo_ct/`. The app now has a CT nodule demo page (`#/ct`): slice
  scroller (mouse wheel or slider), detector boxes with scores, score slider, toggle for the radiologists' marks,
  candidate list, honest summary and credits, labelled PRECOMPUTED DEMO RESULTS. New API: GET /ct-demo, /ct-demo/{case},
  /ct-demo/{case}/slice/{n} (login required, case names strictly validated). Model card has a CT detector section.
  29 tests pass. Side effects in the Daksh Patil Google account: Drive now holds notebooks CellIQ_ct_explore and
  CellIQ_ct_detector (the latter with two extra one-line fix cells).
  Notebook: `ml/CellIQ_ct_detector.ipynb` (fixes above are built in for re-runs).
- **Larger CT detector evaluation (2026-11-13, Colab T4, notebook `ml/CellIQ_ct_eval.ipynb`):** 24 randomly chosen
  LUNA16 subset0 scans (seed 0; only scans whose raw file is <= 120 MB compressed, to keep downloads quick), containing
  27 radiologist-marked nodules in 19 scans. Scans fetched in parallel from the remote zip (1.46 GB in about 1 minute);
  detection took 808 s. FROC (LUNA16 rule: detection centre inside the marked nodule's radius): sensitivity 18.5% at
  1/8 and 1/4 false alarms per scan, 70.4% at 1/2, 77.8% at 1, 85.2% at 2, 88.9% at 4 and 8; CPM 0.640. 95% bootstrap
  intervals (resampling scans): 44.9-91.3% at 0.5 FP/scan, 61.4-94.9% at 1 FP/scan, 64.9-95.8% at 2 FP/scan. By score
  threshold: >= 0.9 finds 77.8% with 1.33 false alarms per scan; >= 0.7 81.5% with 1.96; >= 0.5 85.2% with 2.54; >= 0.1
  88.9% with 5.25. Caveats: the 'irrelevant findings' list (annotations_excluded.csv) was not in Zenodo's records, so real
  small nodules that the reference omits count as false alarms (false alarms are overstated); only 27 nodules, so the
  intervals are wide; the sample excludes the biggest scans; subset0 is believed (not verified) to be held out. This
  replaces the earlier 5-of-8 estimate (4 scans) as the headline number. Result zip (32 KB: eval_summary.json, froc.png)
  was downloaded to `demo_ct/eval/` and the CT demo page and model card now show these numbers (new endpoint
  GET /ct-demo/eval/froc.png; 29 tests pass). Note: froc.png joins the measured operating points with straight lines, so
  read the table, not the low-false-alarm part of the curve. Google side effects: the Daksh Patil Drive also holds
  the notebook CellIQ_ct_eval.
- Overall honest position: the pipeline (data, training, evaluation, explainability, app) works end to end, but our own
  tests show both models rely on shortcuts (CT: image borders; tissue: colour and duplicated slides). Real fixes need
  more diverse data and lesion-level annotations (e.g. LUNA16/LIDC-IDRI).

Not yet done: threshold choice, calibration, threshold choice for 95% sensitivity, calibration,
metrics.json export, wiring real models into the API.

## 6. Strengths

- Clear architecture: a standalone API with a built-in UI, so a custom website can replace the UI later.
- Responsible design: disclaimer on every screen and report, placeholder results clearly flagged, "cannot assess" guard,
  doctor review of AI results, audit log, report must be approved before download or email.
- Privacy: nothing identifying goes to Gemini, notes are scrubbed, scans are never emailed, uploads are re-encoded
  (strips metadata), email defaults to outbox mode, per-doctor hourly send limit.
- Security basics: hashed passwords, role checks on the server, signed tokens, content security policy on the UI,
  all server data inserted as text (no injection).
- Tested: 25 automated tests covering roles, uploads, bad files, notes, reviews, reports, email, dashboard.
- The training notebook is well structured: transfer learning, two-phase training, class weights, train/val/test split,
  sensitivity and specificity, confusion matrix, Grad-CAM and a failure gallery.
- We tested our own model's weakness (the grayscale check) instead of only quoting the headline score.

## 7. Weaknesses and limitations (say these honestly)

1. **Placeholder AI in the app.** Until real models are wired in, scores and heatmaps have no medical meaning.
2. **LC25000 is inflated.** About 750 original photos augmented into ~13,500 lung images, so near-copies sit in both
   training and test. 100% accuracy and zero errors do not show real-world performance.
3. **Colour reliance.** Accuracy dropped to 90.4% without colour. The model partly uses stain colour. (A drop is also
   expected because it never saw grayscale in training, so this test is suggestive, not conclusive.)
4. **Heatmaps are unconvincing.** Several highlighted tissue edges, corners or diffuse areas, not clear cancer nuclei.
   Grad-CAM is coarse. It shows where the model looked, not that it is right.
5. **No independent validation.** No hospital data and no test on a different source yet.
6. **Slide types, not cancer cells.** The tissue model sorts whole images into three types. We cannot claim it
   "finds cancer cells" or "detects cancer".
7. **CT data limits (expected).** IQ-OTH/NCCD has about 110 patients and roughly 1,200 slices, probably without patient
   IDs. The block split only approximates keeping a patient together. The benign group is small, so expect it to be the
   weakest. Metrics will be noisy.
8. **Thresholds and calibration are placeholders.** The 70% and 40% triage cut-offs are not chosen from validation data.
9. **No true localization.** Grad-CAM is not a tumour detector. A real "where is the tumour" answer needs
   location-annotated data (LUNA16/LIDC-IDRI) and a detector.
10. **Demo-only security.** Demo passwords, a random login secret by default, no login rate limiting, no HTTPS.
11. **Not tested yet:** a Gemini-generated report, a real Gmail send, the browser file picker for uploads.
12. **No clinical validation or regulatory review.** Prototype only.

## 8. Safe and unsafe wording

- Say: "flags", "prioritises", "supports clinicians", "classified this dataset's test slides correctly",
  "our scores are likely an upper bound".
- Do not say: "detects cancer", "diagnoses", "finds cancer cells", "100% accurate", "99.8% accuracy" (never measured).
- Only quote numbers that appear in our own results above.

## 9. Next steps

1. Download and save `model.pt`, `meta.json`, `confusion_matrix.png` from `/content/cellIQ_lung_slides` (Colab deletes
   them when the session ends).
2. Train the CT model (`DATASET = "lung_ct"`), save `/content/cellIQ_lung_ct`.
3. Run the CT model on the Kaggle Chest CT-Scan set as an external test and report the drop honestly.
4. Optional: retrain the tissue model with stronger colour augmentation (RandomGrayscale, more saturation/hue jitter)
   and re-run the grayscale check.
5. Add to the notebook: single risk score (1 minus P(normal)), threshold chosen on validation for at least 95%
   sensitivity, calibration, `metrics.json` export.
6. Wire the models into `api/services/ml_service.py` (real inference and Grad-CAM) and fill the model card with
   measured results.
7. Write the 1-page write-up and the 2-minute demo video using real numbers and the limitations above.
8. Before any public hosting: change demo passwords, set a fixed JWT secret, restrict CORS, use HTTPS, add rate limiting.

## Tissue recipe comparison (v2 grayscale-robust notebook vs our tissue_v2)

Notebook: `ml/CellIQ_tissue_compare.ipynb` (run in Colab, T4). Same EfficientNet-B0 and the same LC25000 lung images; the "v2" recipe (50% random grayscale, label smoothing 0.1, cosine schedule, 4 + 8 epochs) was trained twice.

| | A: v2 as written (random split) | B: v2 recipe on our near-duplicate-aware split | Our saved tissue_v2 |
|---|---|---|---|
| Test images | 2026 | 1711 | 1711 |
| Accuracy | 99.95% (1 wrong) | 99.59% (7 wrong) | 99.24% (13 wrong) |
| Accuracy, colour removed | 100% | 99.36% | 98.77% |
| Cancer vs normal sensitivity | 96.4% | 97.6% | 99.7% |
| Cancer vs normal specificity / AUC | 100% / 1.0 | 100% / 1.0 | 100% / 1.0 |
| Test images with a near-identical twin in train (similarity >= 0.90) | 66.6% | 0% | 0% |
| ... at similarity >= 0.85 | 85.2% | 49.7% | 49.7% |

Reading it honestly:
- The v2 notebook as written reports 99.95% only because its random split leaks: two thirds of its test images have a near-identical twin in training. Do not quote that figure.
- On the fair split the v2 recipe is slightly better on accuracy (7 vs 13 wrong) and on the colour-removed test, and slightly worse on cancer-vs-normal sensitivity at the validation-chosen threshold (97.6% vs 99.7%). AUC is 1.0 for both, so the sensitivity gap is mostly where the threshold landed.
- One run each, one public dataset: differences of a few images are within noise, so call them roughly equal. About half the test images still have a similar-looking twin at 0.85, so even 99.6% is probably optimistic.
- Grouping reproduced exactly (similarity 0.9, 5,530 groups, 1,711 test images).

## Tissue model: repeated tests on 3 different test groups, and heatmap check

Notebook: `ml/CellIQ_tissue_robust.ipynb` (Colab, T4). The near-duplicate-aware split has 7 groups; each run trains on 5, validates on 1, tests on 1, and the test group changes between runs (1,711 / 1,802 / 1,813 test images). One training run per recipe per group.

| | Our recipe (the app model) | v2 grayscale-robust recipe |
|---|---|---|
| Accuracy | 99.23% mean (99.11 to 99.45) | 99.75% mean (99.59 to 99.89) |
| Accuracy, colour removed | 98.57% mean (98.22 to 99.23) | 99.55% mean (99.36 to 99.72) |
| Cancer vs normal: sensitivity at the validation-chosen cut-off | 99.6% (99.2 to 100) | 97.1% (96.8 to 97.6) |
| Normal slides correctly cleared / AUC | 100% / 1.0 | 100% / 1.0 |
| Wrong test images (per ~1,800) | 13.7 average (10 to 16) | 4.3 average (2 to 7) |

- The ranges do not overlap on accuracy or colour-removed accuracy, so the v2 recipe is better on these measures across all three test groups. Our own recipe reproduced the saved model (99.12% vs 99.24% on the first group).
- The sensitivity difference is about where the cut-off landed (label smoothing changes the probabilities); AUC is 1.0 for both. A different cut-off rule could recover it.
- Still one public dataset of about 750 original photos; about half of each test group still has a similar-looking twin in training at similarity 0.85. Probably optimistic.

Heatmap check (our recipe, first test group, 600 test images, Grad-CAM):
- Share of the heatmap in the outer 32 px frame: 43% (a uniform heatmap would give 49%), so it is not stuck on image edges.
- Hiding the 20% of pixels the heatmap likes best: 10.1% of correct answers break, confidence drops 0.107.
- Controls: hiding the same amount from another image's heatmap breaks 2.9% (drop 0.036); hiding the least important area breaks 0.3% (drop 0.006).
- Reading: the heatmap marks regions the model really uses (about 3.5 times the effect of a mismatched control), but most answers survive, so the model uses evidence spread over the slide. It does not prove the marked cells are cancer cells.

## Tissue model v3 retrain (2026-11-15)

Notebook: `ml/CellIQ_tissue_v3.ipynb`. Files: `models/tissue_v3_candidate/` (model.pt, meta.json, metrics.json, images) and `models/cellIQ_lung_slides_v3.zip`. NOT yet swapped into the app (the live model is still `models/tissue_v2`).

- Recipe: v2 grayscale-robust (RandomGrayscale 0.5, flip, rot 10, ColorJitter 0.25, label smoothing 0.1, cosine LR, 4 head + 8 fine-tune epochs). Same near-duplicate-aware split as the app model: 5,530 groups, test group 0 = the same 1,711 images (data: 13,501 images).
- Test: accuracy 99.59% (7 wrong: 6 aca->scc, 1 scc->aca, 0 cancers called normal), colour removed 99.36%, AUC 1.0. App model: 99.24% (13 wrong), 98.77%.
- Cancer vs normal: cut-off 0.51 = middle of the cut-offs that best separate normal/cancer on validation (range 0.2 to 0.82). Test: sensitivity 100%, specificity 100%, 0 missed, 0 false alarms. The earlier "highest cut-off for >=99% val sensitivity" rule (0.9) missed 10 cancers on test, and the 95% rule (0.935) missed 50: label smoothing squeezes the scores, so "highest" rules sit at the edge.
- Single run, single test group; same public dataset limits as before (about half of test images still have a similar twin at 0.85). Not clinically validated.
- Gotcha: the Kaggle download holds a small "Test Set" copy (1,499 images) and the full set; `os.walk` can pick either. The v3 notebook picks the folder with the most images and asserts >= 10,000. The older notebooks (tissue_v2, compare, robust) still use "first match".
- The cut-off rule in the notebook was changed after the run (the saved files were re-written in the live session with the new rule), so a rerun may differ in the last digit.

### Swap into the app (2026-11-15, in `cellIQ_edit` only)
- Copied `models/tissue_v3_candidate/*` over `models/tissue_v2/` (loaded by the app from that folder name). The previous app model is kept in `models/tissue_v2_backup_app_model/`.
- `api/services/ml_service.py`: version label "tissue-v3 ..."; review tier 0.50 -> 0.51 (the validated cancer-vs-normal cut-off); high tier stays 0.90 (heuristic; validation cancers scored >= 0.82, normals <= 0.20); uncertainty bands lowered (Low >= 0.85, Medium >= 0.65) because label smoothing caps the top probability near 0.93. The uncertainty bands are heuristics and were not measured on real slides.
- `api/routers/meta.py`: model-card text updated (method, tier note). Test expectations updated. 29 tests pass; the real model loads through the app's own loader.
- Not done: a test with real stained slides in the running app (the dataset is not on this machine), and `cellIQ_original/` still has the old model.

## CT detector improvement test (2026-11-15, 40 LUNA16 subset0 scans)

Notebook: `ml/CellIQ_ct_improve.ipynb` (this run used a copy with N_SCANS = 40, Colab T4, account dakshpatil367). Detector: MONAI lung_nodule_ct_detection, 40 scans in about 24 minutes. 511 candidate detections in total, 34 of them hit a marked nodule (too few real examples to train a filter well). Numbers below were read off the notebook output on screen; the output zip (detections.csv, summary json, FROC plot, rescorer models) was NOT downloaded (needs the user's OK), so it exists only in the Colab runtime.

Share of marked nodules found at 1 false alarm per scan (95% bootstrap range), and CPM:
- Baseline (detector score): 73.2% (62.3 to 87.8%), CPM 0.704. Consistent with the earlier 24-scan result (77.8%, range 61 to 95%).
- Top 1 per scan: 61.0%, clearly worse. Top 2: 70.7%. Top 3: 75.6% (+1.5 points, range includes 0). Top 5 / top 8: same as baseline (73.2%).
- Size model (second-stage, scan-level cross-validation): 68.3%, not better (-5 points, range -12.8 to 0).
- CT model (size + CT values around the candidate): 68.3%, not better.
- Linear CT model: 65.9%, clearly worse (CPM 0.585).

Conclusion: none of the cheap improvements helps. Keep the detector's own score for ranking. The second-stage filter has too little data (34 real candidates) and the detector already returns a short list (about 13 candidates per scan). Honest CT claim stays "about 73 to 78% of marked nodules at 1 false alarm per scan, ranges about 60 to 90%".

Update: the result zip was downloaded and unpacked into `ml/ct_improve_results_40scans/` (improve_summary.json, detections.csv with every raw detection and cross-validated re-scores, froc_variants.png, two rescorer .joblib files that are NOT recommended for use). The saved summary matches the numbers above exactly. Extra facts from it: 40 scans, 28 of them with marked nodules, 41 marked nodules in total.


## CT improvement test (2026-11-15)
Ran `ml/CellIQ_ct_improve.ipynb` (40-scan copy) on a Colab T4: 40 public LUNA16 scans, 28 with marked nodules, 41 marked nodules.
`annotations_excluded.csv` was not found on Zenodo, so false alarms are probably overstated (same caveat as before).
- Baseline (detector score): found 48.8 / 58.5 / 68.3 / 73.2 / 78.0 / 82.9 % of marked nodules at 0.125 / 0.25 / 0.5 / 1 / 2 / 4 false alarms per scan; at 1 per scan 73.2% (range 62.3% to 87.8%); CPM 0.704.
- Top-K per scan at 1 false alarm per scan: K=1 61.0% (clearly worse), K=2 70.7%, K=3 75.6% (+1.5 points, not clearly better), K=5 73.2%, K=8 73.2%.
- Second-stage models (scan-level cross-validation): size model 68.3%, CT-value model 68.3% (CPM 0.662), linear CT model 65.9% (CPM 0.585, clearly worse). None beat the baseline.
Conclusion: no change to the CT detector in the app. The model card now states this. Real-scan CT inference in the app was not built (needs MONAI and about 100 MB of weights locally); the CT page stays a precomputed demo and uploaded CT scans keep the flagged placeholder score.

## Website UI and testing (2026-11-15)
UI rebuilt to the supplied mockups (login, dashboard, upload page; navy sidebar, light content, Outfit font bundled in web/fonts with its OFL licence). Sidebar: Dashboard, Patient Profiles, Upload Scan, Reports, Activity Log, Model Performance. New Reports page; CT demo link moved to Model Performance.
Browser test (radiologist and doctor): login/logout and wrong password, all routes, upload validation, tissue v3 on public test-set samples (normal -> lung_n 94% routine; adenocarcinoma 99% and squamous 98% -> high priority), grayscale/blank/tiny/non-image files rejected, review, notes, visit, report draft/edit/approve, PDF, email outbox, patient search/sort/filter, new patient and edit profile, activity log (now shows user names), CT demo controls, phone-width layout. 29 pytest tests pass.
Test samples came from the same public dataset, so they check the pipeline, not generalisation. Test data was removed afterwards.

## CT nodule detection on uploaded volumes (2026-11-15)
Radiologists can now upload a whole CT volume (.nii, .nii.gz, .mhd/.mha/.nrrd, or a .zip holding a DICOM series or one of those files). `api/services/ct_service.py` validates it (3D, at least 30 slices, Hounsfield-like values, size limits, safe zip extraction), saves a middle-slice preview, then runs the MONAI `lung_nodule_ct_detection` bundle (weights in `models/ct_detector`, 160 MB, Apache-2.0) in a background thread, one scan at a time. Results (JPEG slices and `meta.json`) go to `data/uploads/ct_<scan id>/`; endpoints `GET /scans/{id}/ct` and `/scans/{id}/ct/slice/{i}`; the patient page shows a slice viewer with red boxes, a score slider and a candidate list, and polls while the scan is "processing".
Checked on the public LUNA16 case behind demo case_1 (rebuilt from its 147 JPEG slices as a NIfTI volume): CPU-only run took about 7 minutes; the three highest-scoring detections (scores 1.00, 0.999, 0.997) sit on the three radiologist-marked nodules (25, 11 and 10 mm), and match the earlier Colab run's positions. The fourth Colab detection (score 0.93) scored 0.29 on CPU (fp32 instead of GPU half precision), a reminder that low scores are not stable.
Notes: on a CPU-only PC the weights must be loaded with `map_location="cpu"` and `amp=False` (done in `_run_bundle`). The detector score is not a cancer probability; priority is "priority review" if any candidate scores 0.50 or more, never "high". Single CT images (PNG/JPEG) still get the flagged placeholder score. Torch here is CPU-only (2.15.0+cpu); a GPU would make a scan much faster.
Patient page redesigned (header, fact tiles, scan viewer with heatmap toggle, AI result with plain-language label, doctor review, timeline). Sidebar has a CT Nodule Finder item again. 34 tests pass (5 new in tests/test_ct_upload.py).

## Demo data: new random public scans for every patient (2026-11-15)
Tissue (from Wikimedia Commons, CC licences, and held-out LC25000 samples): all 7 public images were first tested offline. On the 5 outside images the model called 2 normal lungs cancer (alveolar sac: squamous 88%, high priority; normal crop: squamous 54%), called both adenocarcinomas squamous (46% and 64%; still flagged as cancer-type), got the squamous crop right (75%), the mucin-filled alveoli adenocarcinoma 59%, and flagged emphysema for review (normal 47%). Held-out LC25000 samples were correct (adenocarcinoma 97%, normal 96%). Demo patients got a mix (2 held-out, 2 outside) with a note on each patient giving source and true label.
CT (4 random scans from LUNA16 subsets 1 to 4, each with one marked nodule, one per patient, run through the app on CPU, 27 to 57 minutes each): marked nodule located in 3 of 4 by the strict rule (15.1 mm score 1.00; 5.5 mm score 0.999; 27.4 mm score 0.997); the 7.9 mm nodule's top detection (0.997) was about 4 mm from the centre, just outside the 3.95 mm limit. Three extra candidates above 0.5 are not on the reference list.
Downloads are in C:\Users\AMD\Documents\CellIQ\demo_downloads (tissue, ct, source lists).

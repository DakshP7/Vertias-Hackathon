# CT detector weights (not included)

The CT nodule detector is the open-source MONAI `lung_nodule_ct_detection` bundle (v0.6.9, Apache-2.0).
It is about 160 MB, so it is not stored in this repository. To enable CT upload analysis, run from the repo root:

```bash
pip install "monai[all]" SimpleITK
python -m monai.bundle download "lung_nodule_ct_detection" --version "0.6.9" --bundle_dir "./models/ct_detector"
```

This should create `models/ct_detector/lung_nodule_ct_detection/`. Without it the website still works;
CT volume uploads are refused with a message, and the saved example results in `demo_ct/` still display.

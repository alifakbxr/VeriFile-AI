# 🔎 VeriFile AI — Hacktoberfest Hack Day Medan 2026

**Open-source document and transfer-proof forensic triage** with a special focus on **erased/overwritten transfer amounts and evidence photographed from a phone screen** (a scammer deletes `Rp 120.000` and adds `Rp 920.000` over the same background). This is a **functional MVP starter**, **not** a proven fraud detector, AI-origin classifier, or bank transaction verifier.

## What the MVP does

| Engine | What it checks | Status / caveat |
| --- | --- | --- |
| File signatures + SHA-256 | JPG/PNG/WebP/PDF/DOCX; 20 MB cap; detect mismatched extensions | **Working, tested offline** |
| Metadata + chronology | EXIF/XMP/PNG timestamps and software; PDF creator/producer and dates; DOCX creator/last modifier and dates; filesystem times labeled separately | **Working**, but metadata is editable and often absent |
| Screen recapture triage | OpenCV inner-quadrilateral visual cue, camera Make/Model EXIF, exploratory FFT periodicity, preview of candidate border | **Working as uncalibrated review cues**, NOT a reliable screen-photo classifier. No validated moiré/glare inference |
| JPEG ELA | Recompression difference visualization | **Working**, *not* a fraud score |
| PDF paint-order | Detects **text → filled shape → replacement text**, using `Page.get_bboxlog()` | **Working on synthetic vector PDF**; flattened PDFs defeat this test |
| OpenCV amount texture map | Displays spatial image variation and highlights OCR amount regions | **Working, tested offline**; heatmap is not a tamper probability |
| RapidOCR | Detect text line positions and identify potential amount regions (`Rp`, `IDR`, `nominal`, `total`) | **Code connected**; runtime requires `requirements-ocr.txt`, inference **not verified** in this bundle |
| Before/after original | Pixel differences against an **original image of the very same transaction**, same dimensions | **Working, tested offline**, subject to recompression differences |
| Gemma 4 E2B multimodal | Analyzes full image, OCR amount crops, and report JSON; extracts visible transaction fields | **Optional integration**, needs a GPU/model; inference **not verified** in this bundle |
| PhotoHolmes | Additional research-stage forgery localization methods via optional CLI wrapper | **Experimental adapter only**, *not installed or validated* |
| Reports | Local Gradio UI, CLI JSON, and 21 automated offline tests | **Working** |

Do **not** treat heatmaps, metadata, or model judgments as proof of fraud. Some advanced edits are indistinguishable from original pixels once rendered/resaved. A screenshot cannot independently prove a payment was settled; check an authorized bank transaction source.

## 1. Local quick start (no GPU)

Python **3.10–3.12** recommended. RAM ≥8 GB, ~5–10 GB available disk for the **core/OCR mode** (Gemma weights need additional storage). Google Colab is the primary recommended hack-day runtime.

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
python demo/create_samples.py
python -m pytest -q
python app.py
```

To also locate nominal text via CPU OCR:

```bash
pip install -r requirements-ocr.txt
python app.py
```

The OCR package + ONNX engine is optional, but **recommended for Hack Day**. If OCR is unavailable, the app explicitly prints `not_installed`, while all core processing still works.

### Try the erase-and-overwrite attack

Synthetic samples are **not** from a real bank, do not include financial accounts, and cannot confirm any transfer.

1. Upload `demo/edited_sample.jpg`. Optionally provide `demo/clean_sample.jpg` in the **original reference** field. The same-transaction, same-resolution comparison will highlight changed pixels.
2. Upload `demo/edited_overlay_sample.pdf`. It contains the sequence `old amount → white filled rectangle → new amount`, so the PDF paint-order check should report `pdf_text_cover_replace`.
3. Open the forensic heatmap; interpret it only as a way to inspect local image texture. If OCR is installed, amount regions are outlined and passed to Gemma as crops.
4. Download JSON, inspect `forensics.overlay_diagnostics`, `forensics.reference_comparison` and `forensics.findings`.

### Try screen recapture diagnostics (HP screen photographed by a camera)

1. Upload `demo/screen_photo_illustration.jpg`. This is **synthetic artwork**, *not* a real optically photographed display or a moiré dataset; it only tests that the code reports camera EXIF + visible interior quadrilateral as **review**.
2. Inspect `forensics.recapture_diagnostics[0]` in JSON and the screen/paper border overlay in Gradio. It returns `review_possible_screen_recapture` for the illustration. It **does not claim a manipulated screenshot or payment fraud**.
3. For credible evaluation, collect opt-in photographs **actually captured from several phone displays** plus negatives (clean screenshots, photos of paper receipts, app UIs with rectangular panels, compressed/cropped screen photos). Retain labeled ground truth and measure false positives/negatives; do not describe synthetic illustration as a successful real-world detection.
4. If a photo shows a transaction receipt on another phone, EXIF `DateTimeOriginal` (when present) reflects the **camera exposure**, not the creation of the original displayed image nor bank settlement time.

An advanced *research* method is [LC&DF for document presentation attack detection](https://github.com/chenlewis/LC-DF-For-DPAD) (BSD-3-Clause). Its published code uses old PyTorch 1.10.1 / Python 3.7 and separately provided weights; it is **not bundled, installed, or tested**. See `docs/SCREEN_RECAPTURE.md` for the roadmap and limitations.

CLI (single file or multi-file / folder batch export to `.pdf`, `.xlsx`, `.csv`, `.json`):

```bash
# Single file JSON report
python -m verifile.cli demo/edited_overlay_sample.pdf --output report.json

# Batch analyze a whole folder of images/PDFs -> generate visual PDF or Excel (.xlsx) report
python -m verifile.cli "demo/TEST DATA" --ai --output batch_report.pdf
python -m verifile.cli demo/clean_sample.jpg demo/edited_sample.jpg --output batch_report.xlsx
```

## 2. Google Colab / Gemma 4

Open `notebooks/VeriFile_HackDay_Colab.ipynb` in https://colab.research.google.com/ and follow cells in order. It asks you to upload this ZIP, extracts the project, installs OCR + baseline requirements, runs tests, and starts Gradio. No GPU is needed to demonstrate metadata, PDF overlay discovery and reference comparisons.

For optional **Gemma 4 multimodal**:

1. Open https://huggingface.co/google/gemma-4-E2B-it with your Hugging Face account and follow its terms/access requirements.
2. Open Colab **Runtime → Change runtime type → T4 GPU** or any available compatible GPU. Free GPU availability is not guaranteed.
3. Save token under Colab **Secrets → `HF_TOKEN`** (do not write tokens in committed notebooks).
4. In the notebook's Gemma cell, set `ENABLE_GEMMA = True` and run it before starting the UI. The model will be loaded on first request when you check **Gemma 4** in Gradio.
5. The notebook selects 4-bit CUDA quantization by default. This is an experimental optimization, not a guarantee for every Colab/runtime version.

For optional **Gemini API fallback** (when Colab GPU is unavailable or local Gemma fails):

1. Create a Gemini API key in Google AI Studio and save it under Colab **Secrets → `GEMINI_API_KEY`** (or in a local `.env` file copied from `.env.example`).
2. Run Step 3 in `notebooks/VeriFile_HackDay_Colab.ipynb` (or locally `pip install -r requirements-gemini.txt`, though stdlib HTTPS also works without extra packages).
3. When the AI checkbox is enabled in Gradio, `verifile/gemma.py` tries local Gemma 4 first and automatically falls back to `gemini-2.5-flash` (`status: "completed_gemini_fallback"`), sending the redacted JSON summary and images over HTTPS to Google's Gemini API. Set `GEMINI_ONLY=1` to skip local Gemma entirely.

**Disk requirement:** Standard Gemma 4 E2B weight files may exceed 10 GB, *plus* cache/dependencies. The 5–10 GB space mentioned in the event checklist is **not enough** for a guaranteed local Gemma setup. Prefer Colab with sufficient available storage. We have **not** completed Gemma inference or RapidOCR inference in the authoring environment (package download internet access was unavailable).

- Official Gemma inference guide: https://ai.google.dev/gemma/docs/core/huggingface_inference
- Gemma 4 release notes: https://ai.google.dev/gemma/docs/releases
- MLH organizer resources: https://mlh.link/gemma · https://mlh.link/gemma-quickstart · https://mlh.link/gemma-docs · https://mlh.link/gemma-beginnerguide

## 3. Optional PhotoHolmes research backend

PhotoHolmes is an open-source toolbox of forensic methods (e.g. ZERO, DQ, NoiseSniffer, Splicebuster, CAT-Net, TruFor). An optional local CLI adapter is in `scripts/run_photoholmes.py`. Read **[docs/EXPERIMENTAL_BACKENDS.md](docs/EXPERIMENTAL_BACKENDS.md)** for installation and limitations.

**Licensing warning:** Different methods carry different license obligations. PhotoHolmes framework is Apache-2.0, but TruFor is research/noncommercial-restricted according to PhotoHolmes, so do not imply all downstream methods are compatible with MIT or commercial use.

## 4. Repository structure

```text
app.py                              Gradio interface, optional reference image, recapture outline preview
verifile/forensics.py                File signatures, EXIF/PDF/DOCX, ELA, PDF paint order
verifile/overlay.py                  RapidOCR adapter, amount crops, OpenCV heatmap, reference diff
verifile/recapture.py                Screen photo diagnostics: camera EXIF, quadrilaterals, exploratory FFT
verifile/gemma.py                    Optional Gemma 4 reviewer with strict JSON/inconclusive policy
verifile/cli.py                      Local JSON CLI
scripts/run_photoholmes.py          Optional PhotoHolmes CLI integration (untested)
requirements.txt                    Base + OpenCV (no model downloads)
requirements-ocr.txt                Optional RapidOCR + ONNX Runtime
requirements-gemma.txt              Optional Gemma Transformers and 4-bit
notebooks/VeriFile_HackDay_Colab.ipynb
 demo/create_samples.py              5 synthetic fixtures: clean/edited JPG and PDF plus illustrative photo of phone screen
 tests/                             Offline unit tests
 docs/ETHICS.md                      Responsible use/privacy
 docs/EXPERIMENTAL_BACKENDS.md       External methods and license warning
 docs/ROADMAP.md                     Milestones/benchmark
```

## 5. Hack-day priorities

First, get **21 tests passing in Colab**, including the edited PDF test. Next install RapidOCR and verify **a real end-to-end run** with the synthetic transfer screenshot; adjust text recognition if it misses `Rp` values. Then enable Gemma only if GPU/runtime/disk permit. Finally measure test time, false positives on clean examples, and coverage gaps rather than inventing a detection accuracy percentage. See [docs/ROADMAP.md](docs/ROADMAP.md).

## Privacy and license

All core OCR/model work is local to the host running the Python app. A publicly shared Gradio URL or Colab runtime is **not safe for real customer financial documents**. There is no upload authentication or automated secure cleanup in this hack-day starter. Use synthetic/consented examples only. Code authored for this repo is MIT licensed; model weights and optional forensics dependencies have independent terms.

Event: https://events.mlh.com/events/15226

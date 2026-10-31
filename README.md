# 🔎 VeriFile AI — Hacktoberfest Hack Day Medan 2026

**Open-source document and transfer-proof forensic triage** with a special focus on **erased/overwritten transfer amounts and evidence photographed from a phone screen** (e.g. a scammer replaces `Rp 37.400` with `Rp 60.000` over the same background). This is a **functional forensic triage starter**, **not** a legal proof of fraud, AI-origin classifier, or bank transaction verifier.

---

## What the MVP Does

| Engine | What it checks | Status / Caveat |
| --- | --- | --- |
| **File signatures + SHA-256** | JPG/PNG/WebP/PDF/DOCX; 20 MB cap; extension validation | **Working, tested** |
| **Metadata + Chronology** | EXIF/XMP/PNG timestamps and software; PDF dates/creator; DOCX core properties; filesystem times distinguished | **Working**; metadata is editable and often omitted by messaging apps |
| **Screen Recapture Triage** | OpenCV inner-quadrilateral contour, camera Make/Model EXIF, exploratory FFT periodicity | **Working as uncalibrated review cues**; not an automated screen classifier |
| **JPEG ELA** | Recompression difference visualization | **Working**; diagnostic tool, not an authenticity score |
| **PDF Paint-Order Overlays** | Detects **text → filled shape → replacement text** via `pymupdf` (`page.get_bboxlog()`) | **Working on vector PDFs**; flattened raster PDFs defeat this test |
| **OpenCV Texture Map** | Spatial high-frequency energy map and amount candidate ROI highlighting | **Working**; visual aid to inspect local pixel textures |
| **RapidOCR Engine** | Text extraction and ROI candidate filtering (`Rp`, `IDR`, `nominal`, `total`, `jumlah`) | **Working & verified** with ONNX Runtime PP-OCRv6 models |
| **Reference Comparison** | Pixel differential against the original image; includes **aspect-aligned Lanczos normalization** | **Working & verified** on same-transaction pairs of identical or scaled resolutions |
| **Gemma 4 Multimodal** | Optional vision-language review with strict JSON output and untrusted input boundaries | **Optional integration**, requires GPU (e.g. Colab T4) |
| **Security Hardening** | DoS bounds (PDF dimensions, XML entity protection via `defusedxml`, PII redaction, report TTL cleanup, Bandit SAST) | **Fully integrated & verified** (27 unit tests pass) |
| **Reports & UI** | Gradio web UI, CLI JSON export, and automated test suite | **Working** (27 automated tests passing) |

> **Important:** Do **not** treat heatmaps, metadata, or model outputs as proof of fraud. High-quality digital edits may leave no discernible digital seams once flattened and recompressed. Only an authorized bank transaction ledger or API can settle payment authenticity.

---

## 1. Local Quick Start (No GPU Required)

Python **3.10–3.12** recommended. RAM ≥8 GB.

```bash
# Clone the repository
git clone https://github.com/alifakbxr/VeriFile-AI.git
cd VeriFile-AI

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Install core dependencies + OCR engine
pip install -r requirements-ocr.txt

# Generate synthetic test fixtures and run tests
python demo/create_samples.py
python -m pytest -v

# Launch the Gradio web interface
python app.py
```

### Try the Erase-and-Overwrite Detection

1. **Synthetic Samples:**
   - Upload `demo/edited_sample.jpg`. Provide `demo/clean_sample.jpg` in the **original reference** field to see pixel changes highlighted.
   - Upload `demo/edited_overlay_sample.pdf` to inspect vector paint-order text replacement (`pdf_text_cover_replace`).
2. **Real Test Data Pair:**
   - In `demo/TEST DATA/`, upload `202610300859170551-179341978122122.jpg` (Fake, nominal modified to Rp60.000) as the primary document.
   - Supply `202610300859170551-1793419781221.jpg` (Original, nominal Rp37.400) as the reference.
   - The engine automatically normalizes resolution and pinpoints the manipulated nominal bounding box.

### CLI Usage

```bash
# Analyze a file and export JSON report
python -m verifile.cli demo/edited_overlay_sample.pdf --output report.json

# Optional deep metadata scan using ExifTool (if installed)
python -m verifile.cli demo/clean_sample.jpg --exiftool --output report.json
```

---

## 2. Google Colab / Gemma 4 Multimodal

Open [`notebooks/VeriFile_HackDay_Colab.ipynb`](https://colab.research.google.com/drive/1E6wv2ft5EXBq4_SfTgF3OFXdP93Fhj6A) directly in Google Colab:

1. **Step 1:** Automatically clones the latest repository from GitHub.
2. **Step 2:** Installs dependencies (`requirements-ocr.txt`), builds demo fixtures, and executes all 27 unit tests.
3. **Step 3 (Optional Gemma 4):**
   - Switch Colab runtime: **Runtime → Change runtime type → T4 GPU**.
   - Add your Hugging Face token in Colab **Secrets → `HF_TOKEN`**.
   - Set `ENABLE_GEMMA = True` in the Gemma cell and execute.
4. **Step 4:** Launch the interactive Gradio interface directly within Colab.

---

## 3. Security & Privacy Hardening

VeriFile-AI includes layered defenses designed for handling untrusted document inputs:

- **Static Application Security Testing (SAST):** Integrated automated `bandit` security scanning in GitHub Actions CI (`bandit -r verifile/ app.py -ll`).
- **Resource Exhaustion & DoS Prevention:**
  - Strict 20 MB file size limit (`MAX_FILE_BYTES`).
  - Strict PDF page dimension bounds (`MAX_PDF_DIMENSION_POINTS = 5000`) and adaptive rendering scale matrix to prevent Out-Of-Memory / DoS crashes.
  - Pillow image pixel ceiling (`MAX_PIXELS = 24_000_000`).
- **Safe XML Parsing:** Secured DOCX member extraction and XMP reading with `defusedxml`, rejecting DTD and entity expansions (Billion Laughs / quadratic blowup).
- **PII & Financial Data Masking:** Automated regex redaction (`_redact`) masking 9–20 digit bank account numbers across OCR candidates, PDF selectable text, and DOCX text previews.
- **Temporary Report Storage Isolation:** Reports are saved to a dedicated directory with strict `0700` permissions and automatically pruned after 30 minutes (`_cleanup_old_reports`).
- **Authentication & Network Binding:** Configurable host/port via `VERIFILE_HOST` and `VERIFILE_PORT`, with optional HTTP Basic Auth (`VERIFILE_AUTH_USER` / `VERIFILE_AUTH_PASS`).

---

## 4. Repository Structure

```text
app.py                              Gradio interface, reference diff, auth, and cleanup
verifile/forensics.py                File signatures, metadata triage, PDF/DOCX safety, ELA
verifile/overlay.py                  RapidOCR integration, amount crops, heatmap, reference diff
verifile/recapture.py                Screen-photo triage: camera EXIF, quadrilateral border, FFT
verifile/gemma.py                    Optional Gemma 4 multimodal reviewer with strict JSON schema
verifile/exiftool_scan.py            Optional subprocess ExifTool scanner with version check
verifile/timeline.py                 Timestamp parsing, XMP/tIME extraction, chronology check
verifile/cli.py                      Command-line interface
requirements.txt                    Core dependencies (Pillow, OpenCV, PyMuPDF, defusedxml)
requirements-ocr.txt                RapidOCR + ONNX Runtime engine
requirements-gemma.txt              Optional Gemma Transformers + bitsandbytes
notebooks/VeriFile_HackDay_Colab.ipynb  Interactive Google Colab notebook
demo/create_samples.py              Generates 5 synthetic test fixtures
demo/TEST DATA/                     Real test sample pair (Original vs Fake Rp60.000)
tests/                              Automated unit & security regression test suite (27 tests)
docs/ETHICS.md                      Responsible disclosure & privacy guidelines
docs/EXPERIMENTAL_BACKENDS.md       External backends (PhotoHolmes, RapidOCR)
docs/ROADMAP.md                     Milestones, evaluation metrics, and future scope
docs/SCREEN_RECAPTURE.md            Screen photo threat model and limitations
docs/THREAT_MODEL.md                Attacker patterns and defensive requirements
```

---

## Privacy and License

All core processing runs locally on the executing machine. Do not upload confidential financial records to unauthenticated public links. Code authored for this repository is licensed under the [MIT License](LICENSE).

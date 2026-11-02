# 🔎 VeriFile AI — Hacktoberfest Hack Day Medan 2026

**Automated Digital Forensic Triage & Payment Receipt Verification System** with a core focus on **bank transfer receipts and e-wallet transactions** (JPG, PNG, WebP, PDF, DOCX). Simply upload receipt image(s) — the system automatically detects **Generative AI modifications (C2PA manifests / SynthID watermarks / algorithmic media tags)**, **graphic editing software traces (Photoshop, Canva, GIMP)**, **screen recapture / physical phone screen photographs**, extracts structured transaction data, and verifies **internal arithmetic amount consistency** without requiring an authentic reference file.

---

## Key Features

| Forensic Module | Scope & Detections | Status & Verification |
| --- | --- | --- |
| **Generative AI & C2PA Provenance** | Detection of C2PA manifests (Content Credentials), SynthID watermarks, IPTC `trainedAlgorithmicMedia` tags, Google Generative AI, Midjourney, DALL-E, and Firefly provenance metadata | **Tested & Integrated**; directly detects AI-manipulated images from a single upload without needing original reference |
| **Receipt OCR & Math Consistency** | Extraction of bank/platform (wondr by BNI, BCA, Mandiri, BRI, QRIS, DANA, GoPay), transaction status, timestamp, Ref ID, sender, recipient, and internal arithmetic consistency checks | **Tested & Integrated** via RapidOCR + ONNX Runtime PP-OCRv6 |
| **Graphic Editor Detection** | Artifacts and signatures of Adobe Photoshop, Canva, GIMP, PicsArt, Pixelmator across EXIF/XMP metadata and binary structure | **Tested & Integrated** |
| **Physical Screen Recapture Detection** | Distinguishes photographed physical screens/monitors vs native digital screenshots using interior quadrilateral contours, EXIF camera tags, and FFT frequency cues | **Tested & Integrated** |
| **JPEG ELA & Texture Diagnostics** | Error Level Analysis (ELA) visualization and spatial high-frequency energy mapping on amount regions | **Tested & Integrated** |
| **Reference Comparison (Optional)** | High-precision pixel differential analysis when an authentic original from the same transaction is provided (with Lanczos aspect-aligned normalization) | **Tested & Integrated** |
| **High-Grade Security & Privacy** | Strict file size and resolution DoS limits, safe XML parsing via `defusedxml`, bank account PII masking, 30-minute report TTL cleanup, 100% clean Bandit SAST (0 issues) | **Fully Verified** (48 automated unit & security tests pass) |

> **Integrity Notice:** Digital forensic examination evaluates file integrity, AI/C2PA traces, device metadata, and text consistency. For financial transactions, official bank account statements remain the authoritative source of truth.

---

## 1. Local Quick Start (No GPU Required)

Recommended Python version: **3.10–3.12**.

```bash
# Clone repository
git clone https://github.com/alifakbxr/VeriFile-AI.git
cd VeriFile-AI

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Install core dependencies + RapidOCR engine
pip install -r requirements-ocr.txt

# Generate synthetic fixtures and run test suite
python demo/create_samples.py
python -m pytest -v

# Launch the Gradio web interface
python app.py
```

### Automated Triage Workflow (Single & Multi-Upload)

1. Open the Gradio web interface (`http://localhost:7860`).
2. **Upload or drag-and-drop receipt image(s)** into the input pane.
3. The system immediately outputs:
   - **Color-Coded Verdict Banner:** 🚨 *MANIPULATION / AI DETECTED*, 📱 *PHYSICAL SCREEN PHOTO (RECAPTURE)*, or ✅ *CLEAN DIGITAL SCREENSHOT*.
   - **Receipt Data Breakdown:** Bank/e-wallet, header amount, detailed amounts, total amount, arithmetic consistency verdict, transaction date/time, reference ID, recipient, and sender.
   - **Diagnostic Tabs:** Amount ROI, ELA, Screen Contours, and JSON / Batch Report Exporters.

### CLI Usage (Single File & Batch Export to `.pdf`, `.xlsx`, `.csv`, `.json`)

```bash
# Single file JSON report
python -m verifile.cli demo/edited_overlay_sample.pdf --output report.json

# Optional deep metadata scan using ExifTool (if installed)
python -m verifile.cli demo/clean_sample.jpg --exiftool --output report.json

# Batch analyze a whole folder of images/PDFs -> generate visual PDF or Excel (.xlsx) report
python -m verifile.cli "demo/TEST DATA" --ai --output batch_report.pdf
python -m verifile.cli demo/clean_sample.jpg demo/edited_sample.jpg --output batch_report.xlsx
```

---

## 2. Google Colab / Gemma 4 Multimodal & Gemini API Fallback

Open [`notebooks/VeriFile_HackDay_Colab.ipynb`](https://colab.research.google.com/drive/1E6wv2ft5EXBq4_SfTgF3OFXdP93Fhj6A) directly in Google Colab:

1. **Step 1:** Automatically clones the latest repository from GitHub.
2. **Step 2:** Installs dependencies (`requirements-ocr.txt`), builds demo fixtures, and executes all 48 unit tests.
3. **Step 3 (Optional Gemma 4 GPU):**
   - Switch Colab runtime: **Runtime → Change runtime type → T4 GPU**.
   - Add your Hugging Face token in Colab **Secrets → `HF_TOKEN`**.
   - Set `ENABLE_GEMMA = True` in the Gemma cell and execute.
4. **Step 4:** Launch the interactive Gradio interface directly within Colab.

For optional **Gemini API fallback** (when Colab GPU is unavailable or local Gemma fails):

1. Create a Gemini API key in Google AI Studio and save it under Colab **Secrets → `GEMINI_API_KEY`** (or in a local `.env` file copied from `.env.example`).
2. Run Step 3 in `notebooks/VeriFile_HackDay_Colab.ipynb` (or locally `pip install -r requirements-gemini.txt`, though stdlib HTTPS also works without extra packages).
3. When the AI checkbox is enabled in Gradio, `verifile/gemma.py` tries local Gemma 4 first and automatically falls back to `gemini-2.5-flash` (`status: "completed_gemini_fallback"`), sending the redacted JSON summary and images over HTTPS to Google's Gemini API. Set `GEMINI_ONLY=1` to skip local Gemma entirely.

**Disk requirement:** Standard Gemma 4 E2B weight files may exceed 10 GB, *plus* cache/dependencies. The 5–10 GB space mentioned in the event checklist is **not enough** for a guaranteed local Gemma setup. Prefer Colab with sufficient available storage.

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
verifile/receipt.py                 Indonesian receipt parser and amount consistency checker
verifile/batch.py                   Batch processing and report exporters (PDF, Excel, CSV, JSON)
requirements.txt                    Core dependencies (Pillow, OpenCV, PyMuPDF, defusedxml)
requirements-ocr.txt                RapidOCR + ONNX Runtime engine
requirements-gemma.txt              Optional Gemma Transformers + bitsandbytes
requirements-gemini.txt             Optional Google GenAI SDK
notebooks/VeriFile_HackDay_Colab.ipynb  Interactive Google Colab notebook
demo/create_samples.py              Generates 5 synthetic test fixtures
demo/TEST DATA/                     Real test sample pair (Original vs Fake Rp60.000)
demo/TEST FK/                       Additional test fixtures
tests/                              Automated unit & security regression test suite (48 tests)
docs/ETHICS.md                      Responsible disclosure & privacy guidelines
docs/EXPERIMENTAL_BACKENDS.md       External backends (PhotoHolmes, RapidOCR)
docs/ROADMAP.md                     Milestones, evaluation metrics, and future scope
docs/SCREEN_RECAPTURE.md            Screen photo threat model and limitations
docs/THREAT_MODEL.md                Attacker patterns and defensive requirements
```

---

## Privacy and License

All core processing runs locally on the executing machine. Do not upload confidential financial records to unauthenticated public links. Code authored for this repository is licensed under the [MIT License](LICENSE).

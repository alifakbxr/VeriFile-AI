# 🔎 VeriFile AI — Hacktoberfest Hack Day Medan 2026

**Sistem Deteksi Otomatis Integritas Bukti Transfer & Struk Pembayaran (Single-Upload Forensics)** dengan fokus utama pada **bukti transfer bank / dompet digital** (JPG, PNG, WebP). Cukup unggah gambar bukti transfer — sistem langsung mendeteksi rekayasa **Generative AI (C2PA/SynthID)**, **software editor grafis (Photoshop/Canva)**, **foto ulang layar HP (recapture)**, serta mengekstraksi data transaksi dan memverifikasi **konsistensi nominal internal** secara otomatis.

---

## Fitur Utama

| Modul Forensik | Yang Diperiksa & Dideteksi | Status & Bukti Verifikasi |
| --- | --- | --- |
| **Generative AI & C2PA Provenance** | Deteksi manifest C2PA (Content Credentials), watermark SynthID, tag IPTC `trainedAlgorithmicMedia`, Google Generative AI, Midjourney, DALL-E, Firefly | **Teruji & Terintegrasi**; langsung mendeteksi gambar rekayasa AI dari 1 upload tanpa perlu file asli |
| **Ekstraksi Struk & Konsistensi OCR** | Ekstraksi bank/aplikasi (wondr by BNI, BCA, Mandiri, BRI, QRIS, DANA, GoPay), status, waktu, Ref ID, pengirim, penerima, dan pengecekan konsistensi nominal | **Teruji & Terintegrasi** via RapidOCR + ONNX Runtime PP-OCRv6 |
| **Deteksi Software Editor** | Jejak Adobe Photoshop, Canva, GIMP, PicsArt, Pixelmator pada metadata EXIF/XMP maupun binary strings | **Teruji & Terintegrasi** |
| **Deteksi Foto Layar HP (Recapture)** | Deteksi foto ulang monitor/layar HP vs screenshot digital langsung via kontur interior dan EXIF kamera | **Teruji & Terintegrasi** |
| **Diagnostik JPEG ELA & Tekstur** | Visualisasi Error Level Analysis (ELA) dan spatial high-frequency energy map pada area nominal | **Teruji & Terintegrasi** |
| **Perbandingan Referensi (Opsional)** | Analisis perbedaan piksel jika pengguna memiliki file referensi asli transaksi yang sama (dengan normalisasi Lanczos) | **Teruji & Terintegrasi** |
| **Keamanan & Privasi Tingkat Tinggi** | Proteksi DoS ukuran/resolusi file, parsing XML aman via `defusedxml`, penyamaran nomor rekening (PII masking), pembersihan berkas TTL 30 menit, Bandit SAST clean (0 issues) | **Terverifikasi 100%** (34 unit tests pass) |

> **Catatan Integritas:** Pemeriksaan forensik digital mengevaluasi integritas file, jejak AI/C2PA, metadata perangkat, dan konsistensi teks. Untuk transaksi finansial, konfirmasi mutasi rekening bank resmi tetap merupakan sumber kebenaran mutlak.

---

## 1. Quick Start Lokal (Tanpa Butuh GPU)

Direkomendasikan Python **3.10–3.12**.

```bash
# Clone repository
git clone https://github.com/alifakbxr/VeriFile-AI.git
cd VeriFile-AI

# Buat dan aktifkan virtual environment
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Install dependensi inti + RapidOCR
pip install -r requirements-ocr.txt

# Buat sample sintetis dan jalankan unit tests
python demo/create_samples.py
python -m pytest -v

# Jalankan antarmuka Gradio
python app.py
```

### Alur Deteksi Otomatis (Single Upload)

1. Buka antarmuka Gradio (`http://localhost:7860`).
2. **Cukup unggah atau paste gambar bukti transfer** pada kotak utama.
3. Sistem langsung menghasilkan:
   - **Verdict Banner Berwarna:** 🚨 *REKAYASA / MANIPULASI TERDETEKSI*, 📱 *FOTO ULANG LAYAR HP*, atau ✅ *SCREENSHOT DIGITAL BERSIH*.
   - **Ringkasan Data Struk:** Bank/e-wallet, nominal header, rincian nominal, total, status konsistensi nominal, tanggal/waktu, No. Ref, penerima, dan pengirim.
   - **Tab Diagnostik:** ROI Area Nominal, ELA, Kontur Layar, dan Ekspor Laporan JSON.

### CLI Usage (Single File & Batch Export ke `.pdf`, `.xlsx`, `.csv`, `.json`)

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

## 2. Google Colab / Gemma 4 Multimodal

Open [`notebooks/VeriFile_HackDay_Colab.ipynb`](https://colab.research.google.com/drive/1E6wv2ft5EXBq4_SfTgF3OFXdP93Fhj6A) directly in Google Colab:

1. **Step 1:** Automatically clones the latest repository from GitHub.
2. **Step 2:** Installs dependencies (`requirements-ocr.txt`), builds demo fixtures, and executes all 27 unit tests.
3. **Step 3 (Optional Gemma 4):**
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
requirements.txt                    Core dependencies (Pillow, OpenCV, PyMuPDF, defusedxml)
requirements-ocr.txt                RapidOCR + ONNX Runtime engine
requirements-gemma.txt              Optional Gemma Transformers + bitsandbytes
notebooks/VeriFile_HackDay_Colab.ipynb  Interactive Google Colab notebook
demo/create_samples.py              Generates 5 synthetic test fixtures
demo/TEST DATA/                     Real test sample pair (Original vs Fake Rp60.000)
tests/                              Automated unit & security regression test suite (34 tests)
docs/ETHICS.md                      Responsible disclosure & privacy guidelines
docs/EXPERIMENTAL_BACKENDS.md       External backends (PhotoHolmes, RapidOCR)
docs/ROADMAP.md                     Milestones, evaluation metrics, and future scope
docs/SCREEN_RECAPTURE.md            Screen photo threat model and limitations
docs/THREAT_MODEL.md                Attacker patterns and defensive requirements
```

---

## Privacy and License

All core processing runs locally on the executing machine. Do not upload confidential financial records to unauthenticated public links. Code authored for this repository is licensed under the [MIT License](LICENSE).

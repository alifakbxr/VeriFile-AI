# Roadmap — measurable fraud evidence analysis

## M0 — Hack Day, code starter (implemented with bounded scope)
- [x] File-type signatures, SHA-256, bounded JPG/PNG/WebP/PDF/DOCX parsing, metadata
- [x] ELA visualization for JPEG (not used for verdict)
- [x] PDF paint-order text→cover→text candidate detector, with synthetic positive/negative tests
- [x] OpenCV texture map, reference-image pixel difference, ROI crop utilities
- [x] Screen-photo recapture **cues** (camera EXIF + rectangular contour + FFT metrics); explicitly uncalibrated, not a detector of fraudulent content
- [x] Optional RapidOCR adapter (boxes, texts, confidence) and amount ROI localization
- [x] Optional Gemma 4 E2B multimodal integration and ROI crop input
- [x] Demo UI, CLI, JSON export, 4 synthetic images/PDFs, 11 baseline tests
- [x] Optional PhotoHolmes CLI adapter and restrictive-license warning
- [ ] Run RapidOCR models in Colab and verify OCR extraction from demo sample (no OCR runtime in authoring environment)
- [ ] Run Gemma inference on Colab GPU; retain logs and correctly parse JSON responses
- [ ] Evaluate false positives on clean receipt templates and OCR misses (not yet measured)

## M1 — targeted screenshot overwriting benchmark
- [ ] Build 100+ properly consented/synthetic receipt pairs across multiple **fictional templates**, fonts, and file formats
- [ ] Ground-truth edit masks and type labels: white paint/overlay, clone/stamp, heal, inpainting, crop, retouch, recompression, AI-generated entire screenshot
- [ ] Compare PhotoHolmes ZERO, DQ, NoiseSniffer, Splicebuster, TruFor (subject to licenses/resources); measure differences *on transfer screenshots specifically*
- [ ] Explore baseline-free edit localization models with reproducible pretrained model downloads and benchmarks
- [ ] Add region-based typography inconsistency tests (font size, baseline, horizontal alignment, glyph thickness)
- [ ] OCR cross-check for amount, recipient, bank, transfer status, date, and reference, against trusted independent evidence when available
- [ ] Output localization heatmap and measured confidence **only after calibration**
- [ ] Stratify results by export history: JPEG↔PNG, messenger recompression, screenshot cropping, blurred/degraded quality
- [ ] Measure image-level recall, FPR, false accusations, region-level IoU, latency and memory

## M1b — screen-recapture evaluation (not included in hack-day starter)
- [ ] Obtain consented real camera shots of actual phone displays across OLED / LCD, brightness levels and camera angles
- [ ] Add hard negative cases: photographed printed receipts, flat screenshot with rectangular UI, glass reflections, frames, QR codes
- [ ] Measure per-device precision/recall, FPR and confidence intervals for screen-recapture alone, not fraud
- [ ] Compare lightweight baseline to [LC&DF](https://github.com/chenlewis/LC-DF-For-DPAD) subject to model-weight licensing, reproducibility and runtime constraints
- [ ] Consider display-object detector, perspective rectification and calibrated moiré detector (none is currently included)
- [ ] Check performance after tight cropping, JPEG compression, demoiréing and messenger re-encoding

## M2 — trustworthy fraud workflows
- [ ] Bank-verified transaction status through user-authorized, approved channels (not from screenshot alone)
- [ ] Provenance checks such as C2PA when a verifiable chain exists; absent manifests are not fraud evidence
- [ ] Signed reports with source hashes, provenance and reproducibility
- [ ] Sandboxed rendering for hostile files, privacy controls, authentication, file deletion/retention policy
- [ ] Training or model evaluation for AI-generated receipt images; avoid universal AI detector claims
- [ ] Manual reviewer approval/appeal and non-defamatory report language

## M3 — expand file types
- [ ] TIFF / HEIC / XLSX / PPTX / signed PDFs / audio & video adapters
- [ ] Dedicated tests and threat models for each, not a blanket claim of all-file support

## Suggested responsibilities for hack day
Forensics: metadata + PDF + CV overlays. AI: OCR + Gemma4 prompt/evaluation. Product: UI/JSON + incident reporting. QA: synthetic data, tests, metrics and limitations.

# Optional open-source forensic backends

## PhotoHolmes (experimental adapter)

Upstream: https://github.com/photoholmes/photoholmes (base framework Apache-2.0).

PhotoHolmes is **not** a checked, default dependency and has **not** been run in this bundle. It includes many forensic methods, useful for evaluating edit-location masks under controlled tests, including ZERO (JPEG grid), DQ (JPEG double quantization), NoiseSniffer, Splicebuster, and neural backends such as TruFor. Some methods need extra pretrained weights and GPU. **Methods have their own licenses**; TruFor has a noncommercial restriction. Review licenses before use or distribution.

From its documented source repo setup (its PyPI install may vary):

```bash
# separate, disposable Python virtual environment is recommended
git clone https://github.com/photoholmes/photoholmes.git
cd photoholmes
pip install -e .
cd ../VeriFile-AI
python scripts/run_photoholmes.py demo/edited_sample.jpg --method zero
```

The adapter calls `photoholmes run zero --output-folder ... image.jpg` in a subprocess and puts output in `photoholmes_results/`. The adapter itself is tested only for syntax; **inference not verified**. Do not claim PhotoHolmes detects overwritten amounts without a targeted bank-receipt benchmark.

## RapidOCR (CPU OCR Engine)

Upstream: https://github.com/RapidAI/RapidOCR (Apache-2.0, review bundled models separately).

```bash
pip install -r requirements-ocr.txt
```

The app calls `RapidOCR()` through `verifile/overlay.py`, uses `result.boxes`, `result.txts`, and `result.scores`, then highlights text associated with `Rp`, `IDR`, `nominal`, `jumlah`, `total`, etc. Tested and verified on ONNX Runtime PP-OCRv6 models. OCR alone does not detect forgeries. When dependency unavailable, JSON reports `not_installed` explicitly, rather than pretending to complete the check.

## Pixel-forensic analysis

Built-in OpenCV engine shows spatial texture variation near amount OCR boxes and can compare an original *from the same transaction*. When resolutions differ slightly due to export scale or device DPI, the engine performs aspect-aligned Lanczos normalization to enable accurate pixel differential analysis. These are diagnostic visualizations, not anomaly likelihoods. Do not compare unrelated bank receipts, different transactions, or wildly different templates as ground truth.

## PDF paint-order inspection

Uses `PyMuPDF Page.get_bboxlog()` to identify the ordered sequence **text → filled shape → text** in overlapping regions. The PDF still needs vector/text objects. A flattened screenshot in a PDF will not reveal this edit history. Also note that authorized forms/templates and legitimate redactions can exhibit the same sequence.

Official PyMuPDF API: https://pymupdf.readthedocs.io/en/latest/functions.html

## Future benchmarking

Create consented/synthetic local edit pairs and pixel-level ground truth masks. Evaluate independently for: hand-made white-cover/overprint, background clone/healing, inpainting, copy-move, JPEG-to-JPEG resave, screenshots exported from editors, and entirely synthetic receipts. Track image-level recall, false positive rate, localization IoU, and performance per bank template and file format. Split by *source/template*, not random images from the same template, to prevent leakage. Until measurements exist, no accuracy claim is warranted.

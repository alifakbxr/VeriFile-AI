# Screen recapture threat model and detector status

**Target:** an edited transfer receipt displayed on a phone and then photographed using another phone. This can hide evidence of previous digital editing.

**What works in this starter (CPU, offline, no model files):**
- Camera `Make`/`Model` EXIF provenance **claim** (neither signed nor verified)
- Candidate interior quadrilaterals and annotated preview using OpenCV
- Exploratory FFT periodicity ratio for manual inspection, never thresholded to an automatic moiré verdict
- Gemma 4 prompt extension to describe possible physical-screen cues versus ordinary screenshots/paper
- JSON `forensics.recapture_diagnostics[]`, UI marker, regression tests and synthetic illustration

**What is NOT implemented:** calibrated screen-photo classification, trained moiré detector, real reflection/banding detection, device identification, liveness checks, re-projection-based attack localization, and bank transaction verification. A visible rectangle may be a paper receipt. Camera EXIF can be absent or forged. A screenshot can contain visible rectangular UI elements. Strongly cropped photos can be impossible to distinguish from screenshots without trustworthy capture provenance.

**Risks:** reporting a legitimate photo of a screen as fraudulent (false accusation), treating `DateTimeOriginal` as a transaction time, using FFT peaks from fonts as moiré evidence, and assuming absence of clues means the file was not recaptured.

**Reference open-source specialized method:** [LC&DF DPAD](https://github.com/chenlewis/LC-DF-For-DPAD) (BSD-3-Clause); research code based on Python 3.7 and PyTorch 1.10.1 with external pretrained checkpoints. Do not silently make it a dependency on modern Colab. Verify model weight license and reproduce on a separate environment before proposing integration.

**Recommended evaluation:** collect authorized real phone-screen photos and paired screenshot source files. Split by display model and camera model (no identity leakage) and compare to negative sets of clean screenshots / paper document photos / ordinary camera photos. Measure recall and **false positive rate** separately. Test with moiré reduction, crop, social-network JPEG conversion and low light. Show the uncertainty and request issuer verification rather than returning a fraud conviction.

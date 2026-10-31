# Attacker patterns in forged transfer receipts

Primary target: screenshots or PDFs presented as proof of funds sent. The app must **not infer payment settlement** from a picture.

1. **Amount overwrite:** cover old amount with solid-color or cloned background; write new amount and re-export. For image screenshots, inspect potential amount regions and optional before/after original. For PDF vectors, inspect paint order. Without original, may be impossible to distinguish a well-executed edit.
2. **Recipient/account overwrite:** same technique for name/account number; requires OCR with careful masking and bank-side confirmation.
3. **Status altered to `Sukses`:** requires comparison against authorized bank ledger; visual consistency alone insufficient.
4. **Date/time/reference ID edits:** compare with trusted external records if available, not model assertions.
5. **Full fabricated UI:** HTML screenshot, fake app design or generative AI can be internally consistent and leave no digital edit seams. In general, only trusted issuer validation can settle authenticity.
6. **Edited PDF with retained vector objects:** may keep a recoverable text/drawing order, detectable by `Page.get_bboxlog` but not guaranteed.
7. **Flattened PDF:** often only raster image; OCR/image pipeline applies; vector paint order unavailable.
8. **Screen recapture / laundering an edit:** scammer edits a nominal on-screen, then photographs a phone displaying the doctored proof. A new camera JPEG may erase edit metadata and the previously visible local image artifacts. Triage indicators include camera EXIF, display-like contours and context from Gemma; **none is authoritative**, and a photographed legitimate transfer is also possible. Uploaded camera date refers to taking the photo, not when the transfer occurred.
9. **Metadata removal/fabrication:** common legitimate behavior during export, sharing, and privacy-protecting tools; never an allegation by itself.

### Operator & Pipeline Defenses

- **Input bounds:** 20 MB file cap (`MAX_FILE_BYTES`), 24 MP limit (`MAX_PIXELS`), and strict PDF page dimension bounds (`MAX_PDF_DIMENSION_POINTS = 5000`) to mitigate Denial of Service (DoS) and out-of-memory crashes.
- **XML safety:** Member XML files in DOCX archives are defused via `defusedxml`, blocking nested DTDs and entity expansion attacks (Billion Laughs / quadratic blowup).
- **PII masking:** Account and card numbers (9–20 digits) are automatically masked in diagnostic outputs across OCR candidates, PDF text streams, and DOCX document previews.
- **Temporary storage hygiene:** Exported reports are isolated to a directory with `0700` permissions and pruned after 30 minutes via automated TTL cleanup.
- **Access control:** Configurable interface binding and optional HTTP Basic Auth for network deployments (`VERIFILE_AUTH_USER` / `VERIFILE_AUTH_PASS`).
- **Chain of custody:** Never publish confidential financial documents on public Gradio links, and never assume a reference is genuine without independent verification from an authorized banking institution.

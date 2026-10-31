# Responsible use and limitations

- **Not a bank transaction verification system.** A screenshot can faithfully depict a fabricated interface, and a genuine screenshot can be cropped, compressed, or anonymized. Independently verify payment with the recipient's bank or authorized payment system.
- **Do not accuse users of fraud** based on AI output, EXIF absence, ELA, creator metadata, or other single indicators. Display observations and alternative explanations.
- **AI-origin classification is not implemented.** The model may describe generative artifacts, but generation provenance is **not provable** from appearance alone. C2PA/cryptographic provenance can provide supporting information but missing credentials are not evidence of AI generation.
- For hack-day demos, use the synthetic samples. Don't publish real transaction screenshots, identities, account numbers or receipts in issue trackers.
- Uploaded content is handled locally in the Python runtime. Dedicated report storage is scoped with 0700 permissions and automatic TTL pruning. Do not use unauthenticated public Gradio share URLs for sensitive documents; configure `VERIFILE_AUTH_USER` / `VERIFILE_AUTH_PASS` for protected access.
- Files are size-limited and rendered through third-party libraries, but this does **not** constitute secure malware scanning; use isolation/sandboxing before opening arbitrary untrusted documents in production.
- OCR and author metadata can be absent or incorrect, and PDF may be signed but not evaluated for signature validity.
- Model is optional and weights retain their upstream terms; repo license applies to our code only.

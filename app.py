"""Gradio browser demo; all uploaded bytes processed on the running Python host."""
import json
import os
import tempfile
import time
from pathlib import Path

from PIL import Image
import gradio as gr

from verifile.batch import (
    analyze_batch,
    export_batch_csv,
    export_batch_excel,
    export_batch_json,
    export_batch_pdf,
    format_batch_markdown,
)
from verifile.forensics import UnsafeFile, analyze_file, MAX_FILE_BYTES
from verifile.overlay import render_diagnostic_preview, amount_crops, compare_with_reference
from verifile.gemma import Gemma4Reviewer
from verifile.recapture import inspect_screen_recapture

reviewer = Gemma4Reviewer()

REPORTS_DIR = Path(tempfile.gettempdir()) / 'verifile_reports'
REPORTS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
try:
    os.chmod(REPORTS_DIR, 0o700)
except OSError:
    pass


def _restrict_file(path: str | Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _new_report_path(suffix: str, tag: str = 'verifile-report-') -> Path:
    fd, raw = tempfile.mkstemp(suffix=suffix, prefix=tag, dir=REPORTS_DIR)
    os.close(fd)
    _restrict_file(raw)
    return Path(raw)


def _cleanup_old_reports(max_age_seconds: int = 1800, max_files: int = 80) -> None:
    """Purge stale forensic reports to prevent disk exhaustion and data lingering."""
    try:
        now = time.time()
        files = sorted(REPORTS_DIR.glob('verifile-report-*'), key=lambda p: p.stat().st_mtime)
        for f in list(files):
            if now - f.stat().st_mtime > max_age_seconds or len(files) > max_files:
                try:
                    f.unlink(missing_ok=True)
                    files.remove(f)
                except OSError:
                    pass
    except OSError:
        pass


def analyze_ui(path, reference_path, use_gemma, use_exiftool):
    if not path:
        return 'Silakan unggah file.', {}, None, None, None, None, None
    try:
        report, pages, ela = analyze_file(path, reference_path=reference_path, use_exiftool=use_exiftool)
        overlay_view = None
        reference_view = None
        crops = []
        recapture_view = None
        if pages:
            candidates = report['forensics']['overlay_diagnostics'][0]['amount_candidates']
            overlay_view = render_diagnostic_preview(pages[0], candidates)
            crops = amount_crops(pages[0], candidates)
            recapture_view = inspect_screen_recapture(pages[0])[1]
        if reference_path and pages and report['forensics']['reference_comparison']['status'] == 'completed':
            with Image.open(reference_path) as original:
                reference_view = compare_with_reference(pages[0], original)[1]
        if use_gemma:
            try:
                # Original full view + up to 2 focused amount crops within the model's 3-image cap.
                report['gemma4'] = reviewer.review(report, pages[:1] + crops[:2] if crops else pages[:3])
            except Exception as exc:
                report['gemma4'] = {'status': 'error', 'model': reviewer.model_id,
                                    'analysis': {'error': f'{type(exc).__name__}: {exc}'[:800]}}
        found = report['forensics']['findings']
        ocr = report['forensics']['overlay_diagnostics']
        status = ocr[0]['status'] if ocr else 'no_visual_input'
        detected = sum(len(item['amount_candidates']) for item in ocr)
        recaptures = report['forensics'].get('recapture_diagnostics', [])
        recapture_status = recaptures[0]['status'] if recaptures else 'no_visual_input'
        timeline = report['forensics']['timeline']
        created = timeline.get('created')
        modified = timeline.get('modified')
        format_stamp = lambda entry: (f"`{entry['normalized_iso']}` ({entry['source']})"
                                      if entry else '**tidak tersedia**')
        date_section = (f"**Dibuat/diambil:** {format_stamp(created)}\n\n"
                        f"**Terakhir diedit (metadata):** {format_stamp(modified)}\n\n"
                        f"**Kronologi metadata:** `{timeline['chronology']}`\n\n"
                        '> Tanggal berasal dari klaim metadata internal; waktu upload/Colab bukan waktu pembuatan asli. '
                        'Pada foto layar, waktu EXIF kamera merujuk pengambilan foto, bukan waktu transaksi bank.\n\n')
        ai_report = report['gemma4']
        ai_label = ai_report['status']
        if ai_report.get('provider') == 'gemini_api' and ai_report.get('model'):
            ai_label = f"{ai_label} ({ai_report['model']})"
        ai_summary = (ai_report.get('analysis') or {}).get('summary') if isinstance(ai_report.get('analysis'), dict) else None
        ai_section = f"\n\n**Ringkasan AI (`{ai_report.get('model') or 'n/a'}`):** {ai_summary}" if ai_summary else ''
        markdown = (f"### Hasil: {report['forensics']['summary']}\n"
                    f"**Jenis:** `{report['file']['type_detected']}` · "
                    f"**SHA-256:** `{report['file']['sha256']}`\n\n"
                    f"**OCR:** `{status}` · **ROI calon nominal:** {detected} · "
                    f"**AI Multimodal:** `{ai_label}` · **Foto layar:** `{recapture_status}`\n\n"
                    + date_section + "**Indikator**\n" + ('\n'.join(
                        f"- **{f['title']}** ({f['severity']}): {f['detail']}" for f in found)
                        if found else '- Tidak ada temuan dari pemeriksaan terbatas.')
                    + ai_section +
                    "\n\n> **Heatmap bukan peluang pemalsuan.** Validasi transaksi tetap melalui bank.")
        _cleanup_old_reports()
        out_path = _new_report_path('.json')
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        _restrict_file(out_path)
        return markdown, report, ela, overlay_view, reference_view, recapture_view, str(out_path)
    except (UnsafeFile, OSError, ValueError) as exc:
        return f'**Tidak dapat memproses file:** {exc}', {}, None, None, None, None, None


def analyze_batch_ui(file_paths, use_gemma, use_exiftool, ai_max_files, ai_delay_seconds):
    if not file_paths:
        return 'Silakan unggah minimal 1 berkas pada tab Batch.', {}, None, None, None, None
    try:
        batch_result, thumbs = analyze_batch(
            file_paths,
            use_ai=bool(use_gemma),
            use_exiftool=bool(use_exiftool),
            ai_max_files=int(ai_max_files),
            ai_delay_seconds=float(ai_delay_seconds),
            reviewer=reviewer,
        )
        _cleanup_old_reports()
        pdf_path = export_batch_pdf(batch_result, _new_report_path('.pdf', 'verifile-report-batch-'), thumbnails=thumbs)
        xlsx_path = export_batch_excel(batch_result, _new_report_path('.xlsx', 'verifile-report-batch-'))
        csv_path = export_batch_csv(batch_result, _new_report_path('.csv', 'verifile-report-batch-'))
        json_path = export_batch_json(batch_result, _new_report_path('.json', 'verifile-report-batch-'))
        for p in (pdf_path, xlsx_path, csv_path, json_path):
            _restrict_file(p)
        return (
            format_batch_markdown(batch_result),
            batch_result,
            str(pdf_path),
            str(xlsx_path),
            str(csv_path),
            str(json_path),
        )
    except (UnsafeFile, OSError, ValueError) as exc:
        return f'**Gagal memproses batch:** {exc}', {}, None, None, None, None


def build_app():
    with gr.Blocks(title='VeriFile AI — Transfer Screenshot Forensics') as app:
        gr.Markdown('# 🔎 VeriFile AI\n**Deteksi penimpaan nominal dan foto layar HP** · JPG/PNG/WebP/PDF/DOCX · RapidOCR + OpenCV + Gemma 4 / Gemini Fallback')
        gr.Markdown('Diproses di runtime Python (jika fallback Gemini API aktif dan dicentang, gambar dikirim ke Gemini API). '
                    'Jangan upload bukti transfer sensitif ke demo publik. '
                    'Tidak ada verdict fraud otomatis; heatmap hanya panduan inspeksi visual.')

        with gr.Tabs():
            with gr.Tab('Analisis Satuan (1 Berkas)'):
                with gr.Row():
                    with gr.Column():
                        inp = gr.File(label='Unggah bukti transfer / dokumen (maks. 20 MB)',
                                      file_types=['.jpg', '.jpeg', '.png', '.webp', '.pdf', '.docx'],
                                      type='filepath')
                        reference = gr.File(label='Opsional: file ASLI transaksi yang sama, sebelum edit (gambar dan resolusi identik)',
                                            file_types=['.jpg', '.jpeg', '.png', '.webp'], type='filepath')
                        gemma_check = gr.Checkbox(value=False, label='Jalankan AI multimodal (Gemma 4 lokal GPU; otomatis fallback ke Gemini API bila GEMINI_API_KEY diset)')
                        deep_check = gr.Checkbox(value=False, label='Scan ExifTool tambahan (opsional, jika terinstal)')
                        run = gr.Button('Analisis bukti transfer dan sumber foto', variant='primary')
                    with gr.Column():
                        result_text = gr.Markdown('Hasil analisis akan muncul di sini.')
                with gr.Row():
                    overlay_img = gr.Image(label='Diagnostik tekstur + area nominal (BUKAN probabilitas pemalsuan)', type='pil')
                    difference_img = gr.Image(label='Perbedaan terhadap file asli yang sama (jika ada)', type='pil')
                    ela = gr.Image(label='ELA untuk JPEG (diagnostik saja)', type='pil')
                    recapture_img = gr.Image(label='Kontur kandidat layar/kertas (bukan bukti foto layar)', type='pil')
                json_view = gr.JSON(label='Laporan audit JSON')
                downloadable = gr.File(label='Unduh laporan JSON')
                run.click(analyze_ui, inputs=[inp, reference, gemma_check, deep_check],
                          outputs=[result_text, json_view, ela, overlay_img, difference_img, recapture_img, downloadable])

            with gr.Tab('Analisis Batch (Banyak Gambar → PDF / Excel)'):
                with gr.Row():
                    with gr.Column():
                        batch_inp = gr.File(
                            label='Unggah banyak bukti transfer / dokumen sekaligus (maks. 50 berkas, @20 MB)',
                            file_count='multiple',
                            file_types=['.jpg', '.jpeg', '.png', '.webp', '.pdf', '.docx'],
                            type='filepath',
                        )
                        batch_gemma = gr.Checkbox(
                            value=False,
                            label='Jalankan AI multimodal pada batch (dibatasi kuota & jeda di bawah)',
                        )
                        with gr.Row():
                            batch_ai_cap = gr.Slider(
                                minimum=1, maximum=30, value=10, step=1,
                                label='Batas maks. berkas AI per batch (proteksi kuota Gemini API)',
                            )
                            batch_ai_delay = gr.Slider(
                                minimum=0.0, maximum=5.0, value=1.5, step=0.5,
                                label='Jeda antar request AI (detik)',
                            )
                        batch_exif = gr.Checkbox(value=False, label='Scan ExifTool tambahan (opsional)')
                        batch_run = gr.Button('Analisis Semua & Buat Laporan PDF / Excel', variant='primary')
                    with gr.Column():
                        batch_md = gr.Markdown('Unggah beberapa berkas lalu klik tombol analisis batch.')
                with gr.Row():
                    batch_pdf_dl = gr.File(label='Unduh Laporan PDF (Ringkasan + Thumbnail Visual)')
                    batch_xlsx_dl = gr.File(label='Unduh Workbook Excel (.xlsx)')
                    batch_csv_dl = gr.File(label='Unduh Ringkasan CSV (.csv)')
                    batch_json_dl = gr.File(label='Unduh Bundle JSON (.json)')
                with gr.Accordion('Detail Audit JSON Batch', open=False):
                    batch_json_view = gr.JSON(label='JSON Batch')
                batch_run.click(
                    analyze_batch_ui,
                    inputs=[batch_inp, batch_gemma, batch_exif, batch_ai_cap, batch_ai_delay],
                    outputs=[batch_md, batch_json_view, batch_pdf_dl, batch_xlsx_dl, batch_csv_dl, batch_json_dl],
                )
    return app


if __name__ == '__main__':
    auth = None
    auth_user = os.getenv('VERIFILE_AUTH_USER')
    auth_pass = os.getenv('VERIFILE_AUTH_PASS')
    if auth_user and auth_pass:
        auth = (auth_user, auth_pass)

    default_host = '0.0.0.0' if os.getenv('COLAB_GPU') else '127.0.0.1'  # nosec
    server_name = os.getenv('VERIFILE_HOST', default_host)
    server_port = int(os.getenv('VERIFILE_PORT', '7860'))
    share = os.getenv('GRADIO_SHARE') == '1'

    build_app().launch(
        server_name=server_name,
        server_port=server_port,
        share=share,
        auth=auth,
        max_file_size='20mb'
    )

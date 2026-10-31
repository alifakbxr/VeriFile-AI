"""Gradio browser demo; all uploaded bytes processed on the running Python host."""
import json
import os
import tempfile
import time
from pathlib import Path

from PIL import Image
import gradio as gr

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


def _cleanup_old_reports(max_age_seconds: int = 1800, max_files: int = 50) -> None:
    """Purge stale forensic reports to prevent disk exhaustion and data lingering."""
    try:
        now = time.time()
        files = sorted(REPORTS_DIR.glob('verifile-report-*.json'), key=lambda p: p.stat().st_mtime)
        for f in files:
            if now - f.stat().st_mtime > max_age_seconds or len(files) > max_files:
                try:
                    f.unlink(missing_ok=True)
                    if f in files:
                        files.remove(f)
                except OSError:
                    pass
    except (OSError, ValueError):
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
                reference_view = compare_with_reference(pages[0], original, allow_rescale=True)[1]
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
        markdown = (f"### Hasil: {report['forensics']['summary']}\n"
                    f"**Jenis:** `{report['file']['type_detected']}` · "
                    f"**SHA-256:** `{report['file']['sha256']}`\n\n"
                    f"**OCR:** `{status}` · **ROI calon nominal:** {detected} · "
                    f"**Gemma 4:** `{report['gemma4']['status']}` · **Foto layar:** `{recapture_status}`\n\n"
                    + date_section + "**Indikator**\n" + ('\n'.join(
                        f"- **{f['title']}** ({f['severity']}): {f['detail']}" for f in found)
                        if found else '- Tidak ada temuan dari pemeriksaan terbatas.') +
                    "\n\n> **Heatmap bukan peluang pemalsuan.** Validasi transaksi tetap melalui bank.")
        _cleanup_old_reports()
        output = tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='verifile-report-',
                                             dir=REPORTS_DIR, delete=False, encoding='utf-8')
        with output:
            json.dump(report, output, indent=2, ensure_ascii=False)
        try:
            os.chmod(output.name, 0o600)
        except OSError:
            pass
        return markdown, report, ela, overlay_view, reference_view, recapture_view, output.name
    except (UnsafeFile, OSError, ValueError) as exc:
        return f'**Tidak dapat memproses file:** {exc}', {}, None, None, None, None, None


def build_app():
    with gr.Blocks(title='VeriFile AI — Transfer Screenshot Forensics') as app:
        gr.Markdown('# 🔎 VeriFile AI\n**Deteksi penimpaan nominal dan foto layar HP** · JPG/PNG/WebP/PDF/DOCX · RapidOCR + OpenCV + Gemma 4')
        gr.Markdown('Diproses di runtime Python. Jangan upload bukti transfer sensitif ke demo publik. '
                    'Tidak ada verdict fraud otomatis; heatmap hanya panduan inspeksi visual.')
        with gr.Row():
            with gr.Column():
                inp = gr.File(label='Unggah bukti transfer / dokumen (maks. 20 MB)',
                              file_types=['.jpg', '.jpeg', '.png', '.webp', '.pdf', '.docx'],
                              type='filepath')
                reference = gr.File(label='Opsional: file ASLI transaksi yang sama, sebelum edit (gambar dan resolusi identik)',
                                    file_types=['.jpg', '.jpeg', '.png', '.webp'], type='filepath')
                gemma_check = gr.Checkbox(value=False, label='Jalankan Gemma 4 multimodal (opsional, butuh GPU/model)')
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

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


def _format_verdict_card(report: dict) -> str:
    category = report.get('verdict_category', 'TIDAK_TERDETEKSI_ANOMALI')
    title = report.get('verdict_title', 'Hasil Pemeriksaan')
    risk = report.get('risk_level', 'RENDAH')
    summary = report.get('forensics', {}).get('summary', '')
    receipt = report.get('receipt_data', {})

    if category == 'MANIPULASI_TERDETEKSI':
        bg = '#fef2f2'
        border = '#dc2626'
        text_color = '#991b1b'
        badge_bg = '#b91c1c'
    elif category == 'FOTO_LAYAR_HP':
        bg = '#f0f9ff'
        border = '#0284c7'
        text_color = '#075985'
        badge_bg = '#0369a1'
    elif category == 'PERLU_VERIFIKASI':
        bg = '#fffbeb'
        border = '#d97706'
        text_color = '#92400e'
        badge_bg = '#b45309'
    else:
        bg = '#f0fdf4'
        border = '#16a34a'
        text_color = '#166534'
        badge_bg = '#15803d'

    card_html = f"""
    <div style="background-color: {bg}; border: 2px solid {border}; border-radius: 12px; padding: 20px 24px; margin-bottom: 16px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 8px;">
            <div style="font-size: 22px; font-weight: 800; color: {text_color};">{title}</div>
            <div style="background-color: {badge_bg}; color: #ffffff; padding: 5px 14px; border-radius: 9999px; font-size: 13px; font-weight: 700; letter-spacing: 0.5px;">RISIKO: {risk}</div>
        </div>
        <div style="color: {text_color}; font-size: 15px; line-height: 1.5; font-weight: 500;">{summary}</div>
    </div>
    """

    if receipt and receipt.get('is_receipt'):
        bank = receipt.get('bank', '-')
        status_tx = receipt.get('transaction_status', '-')
        amounts = receipt.get('amounts', {})
        header_amt = amounts.get('header', '-')
        nominal_amt = amounts.get('nominal', '-')
        total_amt = amounts.get('total', '-')
        dt = receipt.get('date_time', '-')
        ref = receipt.get('ref_id', '-')
        penerima = receipt.get('recipient', '-')
        pengirim = receipt.get('sender', '-')
        consistency = receipt.get('internal_consistency', {})
        cons_status = (
            "<span style='color: #15803d; font-weight: 700;'>✅ Konsisten</span>"
            if consistency.get('is_consistent')
            else f"<span style='color: #b91c1c; font-weight: 700;'>🚨 Tidak Konsisten ({consistency.get('reason', '')})</span>"
        )

        receipt_html = f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 22px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
            <div style="font-weight: 700; color: #1e293b; font-size: 16px; margin-bottom: 14px; border-bottom: 1px solid #f1f5f9; padding-bottom: 8px;">
                🧾 Data Bukti Transfer Terekstraksi (OCR)
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; font-size: 14px; color: #334155;">
                <div><span style="color: #64748b;">Bank / Platform:</span> <br/><strong style="color: #0f172a; font-size: 15px;">{bank}</strong></div>
                <div><span style="color: #64748b;">Status Transaksi:</span> <br/><strong style="color: #0f172a; font-size: 15px;">{status_tx}</strong></div>
                <div><span style="color: #64748b;">Nominal Header:</span> <br/><strong style="color: #0f172a; font-size: 16px;">{header_amt}</strong></div>
                <div><span style="color: #64748b;">Rincian Nominal:</span> <br/><strong style="color: #0f172a; font-size: 16px;">{nominal_amt}</strong></div>
                <div><span style="color: #64748b;">Total:</span> <br/><strong style="color: #0f172a; font-size: 16px;">{total_amt}</strong></div>
                <div><span style="color: #64748b;">Konsistensi Nominal:</span> <br/>{cons_status}</div>
                <div><span style="color: #64748b;">Waktu Transaksi:</span> <br/><strong style="color: #0f172a;">{dt}</strong></div>
                <div><span style="color: #64748b;">No. Referensi:</span> <br/><strong style="color: #0f172a;">{ref}</strong></div>
                <div><span style="color: #64748b;">Penerima:</span> <br/><strong style="color: #0f172a;">{penerima}</strong></div>
                <div><span style="color: #64748b;">Pengirim:</span> <br/><strong style="color: #0f172a;">{pengirim}</strong></div>
            </div>
        </div>
        """
    else:
        receipt_html = ""

    return card_html + receipt_html


def _format_details_markdown(report: dict) -> str:
    found = report['forensics']['findings']
    timeline = report['forensics']['timeline']
    created = timeline.get('created')
    modified = timeline.get('modified')
    format_stamp = lambda entry: (f"`{entry['normalized_iso']}` ({entry['source']})" if entry else '**tidak tersedia**')

    sections = [
        f"**File:** `{report['file']['name']}` ({report['file']['type_detected'].upper()}, {report['file']['bytes'] // 1024} KB) · **SHA-256:** `{report['file']['sha256']}`",
        f"**Waktu Pembuatan (Metadata):** {format_stamp(created)} · **Waktu Modifikasi (Metadata):** {format_stamp(modified)}",
        f"**Kronologi Metadata:** `{timeline['chronology']}`",
        "### 🔍 Temuan Indikator Forensik",
    ]
    if found:
        for f in found:
            sev = f['severity'].upper()
            icon = '🚨' if sev == 'ALERT' else ('⚠️' if sev == 'REVIEW' else 'ℹ️')
            sections.append(f"- {icon} **{f['title']}** [{sev}]: {f['detail']}")
    else:
        sections.append("- ✅ Tidak ada indikator manipulasi yang teridentifikasi.")

    sections.append("\n> 💡 **Prinsip Validasi Finansial:** Pemeriksaan forensik digital mengevaluasi integritas file, jejak AI/C2PA, metadata perangkat, dan konsistensi teks. Validasi keabsahan mutasi finansial resmi tetap disarankan melalui mutasi perbankan.")
    return "\n\n".join(sections)


def analyze_ui(image_path=None, doc_path=None, reference_path=None, use_gemma=False, use_exiftool=False):
    target_path = image_path or doc_path
    if not target_path:
        empty_card = """
        <div style="background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 30px; text-align: center; color: #64748b;">
            <h3 style="margin-top: 0;">Silakan unggah gambar bukti transfer</h3>
            <p>Sistem akan otomatis mendeteksi manipulasi, rekayasa Generative AI (C2PA/SynthID), dan konsistensi nominal transaksi.</p>
        </div>
        """
        return empty_card, '', {}, None, None, None, None, None
    try:
        report, pages, ela = analyze_file(target_path, reference_path=reference_path, use_exiftool=use_exiftool)
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
                report['gemma4'] = reviewer.review(report, pages[:1] + crops[:2] if crops else pages[:3])
            except Exception as exc:
                report['gemma4'] = {'status': 'error', 'model': reviewer.model_id,
                                    'analysis': {'error': f'{type(exc).__name__}: {exc}'[:800]}}

        card_html = _format_verdict_card(report)
        details_md = _format_details_markdown(report)

        _cleanup_old_reports()
        output = tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='verifile-report-',
                                             dir=REPORTS_DIR, delete=False, encoding='utf-8')
        with output:
            json.dump(report, output, indent=2, ensure_ascii=False)
        try:
            os.chmod(output.name, 0o600)
        except OSError:
            pass

        return card_html, details_md, report, overlay_view, ela, recapture_view, reference_view, output.name
    except (UnsafeFile, OSError, ValueError) as exc:
        err_card = f"""
        <div style="background-color: #fee2e2; border: 2px solid #ef4444; border-radius: 12px; padding: 18px 24px; color: #991b1b;">
            <h3 style="margin: 0 0 8px 0;">Tidak Dapat Memproses File</h3>
            <p style="margin: 0;">{exc}</p>
        </div>
        """
        return err_card, f"**Error:** {exc}", {}, None, None, None, None, None


def build_app():
    with gr.Blocks(title='VeriFile AI — Deteksi Bukti Transfer Otomatis', theme=gr.themes.Soft()) as app:
        gr.Markdown(
            "# 🔎 VeriFile AI\n"
            "### Sistem Deteksi Otomatis Integritas Bukti Transfer & Struk Pembayaran\n"
            "Cukup unggah gambar bukti transfer (JPG, PNG, WebP) — sistem akan langsung mendeteksi apakah bukti transfer asli, terindikasi rekayasa Generative AI (C2PA/SynthID), software editor grafis (Photoshop/Canva), foto ulang layar HP, atau inkonsistensi nominal transaksi."
        )

        with gr.Row():
            with gr.Column(scale=5):
                inp = gr.Image(
                    label="📸 Unggah Bukti Transfer (Drag & Drop atau Paste)",
                    type="filepath",
                    sources=["upload", "clipboard"]
                )
                run_btn = gr.Button("🔍 Deteksi Keaslian Bukti Transfer", variant="primary", size="lg")

                with gr.Accordion("⚙️ Opsi Lanjutan & File Dokumen (PDF/DOCX/Referensi)", open=False):
                    doc_inp = gr.File(
                        label="Atau unggah file PDF / DOCX (maks. 20 MB)",
                        file_types=[".pdf", ".docx", ".jpg", ".jpeg", ".png", ".webp"],
                        type="filepath"
                    )
                    reference_inp = gr.Image(
                        label="Opsional: File bukti ASLI transaksi yang sama sebagai pembanding",
                        type="filepath",
                        sources=["upload", "clipboard"]
                    )
                    gemma_check = gr.Checkbox(value=False, label="Gemma 4 Multimodal Verification (opsional, butuh GPU)")
                    deep_check = gr.Checkbox(value=False, label="Deep Scan ExifTool (opsional, jika terpasang)")

            with gr.Column(scale=6):
                verdict_card = gr.HTML(
                    """<div style="background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 30px; text-align: center; color: #64748b;">
                    <h3 style="margin-top: 0;">Belum ada bukti transfer diunggah</h3>
                    <p>Unggah atau paste gambar bukti transfer di sebelah kiri untuk melihat hasil deteksi langsung.</p>
                    </div>"""
                )
                details_text = gr.Markdown()

        gr.Markdown("### 🔬 Visualisasi & Diagnostik Forensik Lanjutan")
        with gr.Tabs():
            with gr.TabItem("🎯 Deteksi Teks & ROI Nominal"):
                overlay_img = gr.Image(label="Area ROI Nominal & Analisis Tekstur Teks", type="pil")
            with gr.TabItem("🔬 Analisis Error Level (ELA)"):
                ela = gr.Image(label="Visualisasi Kompresi JPEG (Error Level Analysis)", type="pil")
            with gr.TabItem("📱 Deteksi Foto Layar HP"):
                recapture_img = gr.Image(label="Kontur Layar / Indikasi Recapture Layar Fisik", type="pil")
            with gr.TabItem("⚖️ Perbandingan Referensi Asli"):
                difference_img = gr.Image(label="Peta Perbedaan Piksel vs Bukti Asli", type="pil")
            with gr.TabItem("📋 Laporan Audit JSON"):
                json_view = gr.JSON(label="Struktur Data Audit Lengkap")
                downloadable = gr.File(label="Unduh Laporan Forensik JSON")

        inputs = [inp, doc_inp, reference_inp, gemma_check, deep_check]
        outputs = [verdict_card, details_text, json_view, overlay_img, ela, recapture_img, difference_img, downloadable]

        run_btn.click(analyze_ui, inputs=inputs, outputs=outputs)
        inp.change(analyze_ui, inputs=inputs, outputs=outputs)

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

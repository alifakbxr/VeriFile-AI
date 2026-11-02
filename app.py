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



def _generate_multi_overview(reports: list[dict]) -> str:
    if not reports or len(reports) <= 1:
        return ""

    total = len(reports)
    manipulated = sum(1 for r in reports if r.get('verdict_category') == 'MANIPULASI_TERDETEKSI')
    recaptured = sum(1 for r in reports if r.get('verdict_category') == 'FOTO_LAYAR_HP')
    clean = sum(1 for r in reports if r.get('verdict_category') == 'TIDAK_TERDETEKSI_ANOMALI')
    review = sum(1 for r in reports if r.get('verdict_category') == 'PERLU_VERIFIKASI')

    overview_html = f"""
    <div style="background-color: #f8fafc; border: 2px solid #64748b; border-radius: 12px; padding: 18px 24px; margin-bottom: 20px;">
        <div style="font-size: 18px; font-weight: 800; color: #0f172a; margin-bottom: 8px;">
            📊 Ringkasan Analisis Multi-Upload ({total} Berkas Dianalisis)
        </div>
        <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px;">
            <span style="background-color: #fee2e2; color: #991b1b; padding: 4px 12px; border-radius: 6px; font-weight: 700; font-size: 13px;">🚨 Manipulasi/AI: {manipulated}</span>
            <span style="background-color: #e0f2fe; color: #075985; padding: 4px 12px; border-radius: 6px; font-weight: 700; font-size: 13px;">📱 Foto Layar: {recaptured}</span>
            <span style="background-color: #fef3c7; color: #92400e; padding: 4px 12px; border-radius: 6px; font-weight: 700; font-size: 13px;">⚠️ Perlu Verifikasi: {review}</span>
            <span style="background-color: #dcfce7; color: #166534; padding: 4px 12px; border-radius: 6px; font-weight: 700; font-size: 13px;">✅ Bersih: {clean}</span>
        </div>
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px; text-align: left;">
                <thead>
                    <tr style="border-bottom: 2px solid #cbd5e1; color: #475569;">
                        <th style="padding: 8px;">Nama Berkas</th>
                        <th style="padding: 8px;">Bank / Platform</th>
                        <th style="padding: 8px;">Nominal</th>
                        <th style="padding: 8px;">Hasil Deteksi</th>
                        <th style="padding: 8px;">Tingkat Risiko</th>
                    </tr>
                </thead>
                <tbody>
    """
    for r in reports:
        name = r.get('file', {}).get('name', 'file')
        receipt = r.get('receipt_data', {})
        bank = receipt.get('bank', '-') if receipt else '-'
        amt = receipt.get('amounts', {}).get('header', '-') if receipt else '-'
        cat = r.get('verdict_category', '')
        title = r.get('verdict_title', '')
        risk = r.get('risk_level', '')

        if cat == 'MANIPULASI_TERDETEKSI':
            color = '#dc2626'
        elif cat == 'FOTO_LAYAR_HP':
            color = '#0284c7'
        elif cat == 'PERLU_VERIFIKASI':
            color = '#d97706'
        else:
            color = '#16a34a'

        overview_html += f"""
                    <tr style="border-bottom: 1px solid #e2e8f0;">
                        <td style="padding: 8px; font-weight: 600;">{name}</td>
                        <td style="padding: 8px;">{bank}</td>
                        <td style="padding: 8px; font-weight: 700;">{amt}</td>
                        <td style="padding: 8px; color: {color}; font-weight: 700;">{title}</td>
                        <td style="padding: 8px;"><span style="color: {color}; font-weight: bold;">{risk}</span></td>
                    </tr>
        """
    overview_html += """
                </tbody>
            </table>
        </div>
    </div>
    """
    return overview_html


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


def analyze_multi_ui(files=None, use_gemma=False, use_exiftool=False):
    if not files:
        empty_card = """
        <div style="background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 30px; text-align: center; color: #64748b;">
            <h3 style="margin-top: 0;">Silakan unggah gambar bukti transfer</h3>
            <p>Pilih atau drag satu atau beberapa bukti transfer (JPG, PNG, WebP) untuk langsung mendeteksi manipulasi, rekayasa Generative AI, dan konsistensi nominal.</p>
        </div>
        """
        return "", gr.Dropdown(choices=[], value=None, visible=False), empty_card, "", None, None, None, None, {}, None, {}

    if isinstance(files, str):
        files = [files]
    else:
        files = list(files)

    items_data = {}
    reports_list = []
    _cleanup_old_reports()

    for path in files:
        if not path:
            continue
        try:
            report, pages, ela = analyze_file(path, use_exiftool=use_exiftool)
            overlay_view = None
            crops = []
            recapture_view = None
            if pages:
                candidates = report['forensics']['overlay_diagnostics'][0]['amount_candidates']
                overlay_view = render_diagnostic_preview(pages[0], candidates)
                crops = amount_crops(pages[0], candidates)
                recapture_view = inspect_screen_recapture(pages[0])[1]
            if use_gemma and pages:
                try:
                    report['gemma4'] = reviewer.review(report, pages[:1] + crops[:2] if crops else pages[:3])
                except Exception as exc:
                    report['gemma4'] = {'status': 'error', 'model': reviewer.model_id,
                                        'analysis': {'error': f'{type(exc).__name__}: {exc}'[:800]}}

            output = tempfile.NamedTemporaryFile(mode='w', suffix='.json', prefix='verifile-report-',
                                                 dir=REPORTS_DIR, delete=False, encoding='utf-8')
            with output:
                json.dump(report, output, indent=2, ensure_ascii=False)
            try:
                os.chmod(output.name, 0o600)
            except OSError:
                pass

            file_key = Path(path).name
            if file_key in items_data:
                file_key = f"{file_key}_{len(items_data)+1}"

            items_data[file_key] = {
                'report': report,
                'page': pages[0] if pages else None,
                'overlay': overlay_view,
                'ela': ela,
                'recapture': recapture_view,
                'report_file': output.name,
            }
            reports_list.append(report)
        except (UnsafeFile, OSError, ValueError) as exc:
            file_key = Path(path).name
            items_data[file_key] = {
                'error': str(exc),
                'report': {'verdict_title': 'Gagal Memproses File', 'verdict_category': 'ERROR', 'risk_level': 'UNKNOWN', 'forensics': {'summary': str(exc), 'findings': []}},
                'page': None, 'overlay': None, 'ela': None, 'recapture': None, 'report_file': None
            }

    if not items_data:
        return "", gr.Dropdown(choices=[], value=None, visible=False), "", "", None, None, None, None, {}, None, {}

    # Auto comparison between uploaded files if 2 files uploaded
    diff_view = None
    if len(files) == 2 and len(items_data) == 2:
        keys = list(items_data.keys())
        p1 = items_data[keys[0]].get('page')
        p2 = items_data[keys[1]].get('page')
        if p1 and p2:
            try:
                comp, diff_img = compare_with_reference(p2, p1, allow_rescale=True)
                if comp.get('status') == 'completed':
                    diff_view = diff_img
            except Exception:
                diff_view = None

    overview_html = _generate_multi_overview(reports_list)
    file_choices = list(items_data.keys())

    # Prioritize flagged/manipulated file as default if present
    default_key = file_choices[0]
    for k in file_choices:
        if items_data[k].get('report', {}).get('verdict_category') == 'MANIPULASI_TERDETEKSI':
            default_key = k
            break

    active = items_data[default_key]
    if 'error' in active:
        card_html = f"<div style='background-color:#fee2e2; border:2px solid #ef4444; border-radius:12px; padding:18px; color:#991b1b;'><h3>Gagal: {default_key}</h3><p>{active['error']}</p></div>"
        details_md = f"**Error:** {active['error']}"
        active_json = {}
        active_file = None
    else:
        card_html = _format_verdict_card(active['report'])
        details_md = _format_details_markdown(active['report'])
        active_json = active['report']
        active_file = active['report_file']

    return (
        overview_html,
        gr.Dropdown(choices=file_choices, value=default_key, visible=len(file_choices) > 1),
        card_html,
        details_md,
        active.get('overlay'),
        active.get('ela'),
        active.get('recapture'),
        diff_view,
        active_json,
        active_file,
        items_data
    )


def on_select_file(selected_name, state_data):
    if isinstance(selected_name, (tuple, list)) and len(selected_name) > 0:
        selected_name = selected_name[0]
    if not state_data or not selected_name or selected_name not in state_data:
        return "", "", None, None, None, {}, None
    active = state_data[selected_name]
    if 'error' in active:
        card_html = f"<div style='background-color:#fee2e2; border:2px solid #ef4444; border-radius:12px; padding:18px; color:#991b1b;'><h3>Gagal: {selected_name}</h3><p>{active['error']}</p></div>"
        return card_html, f"**Error:** {active['error']}", None, None, None, {}, None

    card_html = _format_verdict_card(active['report'])
    details_md = _format_details_markdown(active['report'])
    return (
        card_html,
        details_md,
        active.get('overlay'),
        active.get('ela'),
        active.get('recapture'),
        active.get('report', {}),
        active.get('report_file')
    )


def analyze_ui(path=None, reference_path=None, use_gemma=False, use_exiftool=False):
    """Backward compatibility wrapper for single/reference upload calls."""
    files = [path] if path else []
    if reference_path:
        files.append(reference_path)
    res = analyze_multi_ui(files, use_gemma=use_gemma, use_exiftool=use_exiftool)
    card_html = res[2]
    details_md = res[3]
    overlay_view = res[4]
    ela = res[5]
    recapture_view = res[6]
    diff_view = res[7]
    json_rep = res[8]
    output_name = res[9]
    combined_md = f"{card_html}\n\n{details_md}"
    return combined_md, json_rep, ela, overlay_view, diff_view, recapture_view, output_name


def build_app():
    with gr.Blocks(title='VeriFile AI — Deteksi Bukti Transfer Otomatis', theme=gr.themes.Soft()) as app:
        gr.Markdown(
            "# 🔎 VeriFile AI\n"
            "### Sistem Deteksi Otomatis Integritas Bukti Transfer (Multi-Upload Forensics)\n"
            "Unggah satu atau banyak bukti transfer sekaligus (JPG, PNG, WebP) — sistem akan langsung mendeteksi rekayasa **Generative AI (C2PA/SynthID)**, **software editor grafis (Photoshop/Canva)**, **foto ulang layar HP (recapture)**, serta mengekstrak rincian struk dan memeriksa **konsistensi nominal transaksi** secara otomatis tanpa perlu file pembanding."
        )

        state_store = gr.State({})

        with gr.Row():
            with gr.Column(scale=5):
                inp = gr.File(
                    label="📸 Unggah Bukti Transfer (Bisa pilih/drag banyak berkas sekaligus)",
                    file_count="multiple",
                    file_types=[".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx"],
                    type="filepath"
                )
                with gr.Row():
                    run_btn = gr.Button("🔍 Deteksi Bukti Transfer", variant="primary", size="lg")
                    clear_btn = gr.ClearButton(components=[inp], value="Hapus File")

                with gr.Accordion("⚙️ Opsi Tambahan (Gemma Multimodal / ExifTool)", open=False):
                    gemma_check = gr.Checkbox(value=False, label="Jalankan AI multimodal (Gemma 4 lokal GPU; otomatis fallback ke Gemini API bila GEMINI_API_KEY diset)")
                    deep_check = gr.Checkbox(value=False, label="Deep Scan ExifTool (opsional, jika terpasang)")

            with gr.Column(scale=7):
                multi_overview = gr.HTML()
                file_selector = gr.Dropdown(
                    label="📂 Pilih Berkas untuk Melihat Detail Forensik",
                    choices=[],
                    visible=False,
                    interactive=True
                )
                verdict_card = gr.HTML(
                    """<div style="background-color: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 30px; text-align: center; color: #64748b;">
                    <h3 style="margin-top: 0;">Belum ada bukti transfer diunggah</h3>
                    <p>Pilih atau drag satu atau banyak gambar bukti transfer di sebelah kiri untuk melihat hasil deteksi langsung.</p>
                    </div>"""
                )
                details_text = gr.Markdown()

        gr.Markdown("### 🔬 Visualisasi & Diagnostik Forensik Berkas Terpilih")
        with gr.Tabs():
            with gr.TabItem("🎯 Deteksi Teks & ROI Nominal"):
                overlay_img = gr.Image(label="Area ROI Nominal & Analisis Tekstur Teks", type="pil")
            with gr.TabItem("🔬 Analisis Error Level (ELA)"):
                ela_img = gr.Image(label="Visualisasi Kompresi JPEG (Error Level Analysis)", type="pil")
            with gr.TabItem("📱 Deteksi Foto Layar HP"):
                recapture_img = gr.Image(label="Kontur Layar / Indikasi Recapture Layar Fisik", type="pil")
            with gr.TabItem("⚖️ Perbandingan Antar Berkas"):
                difference_img = gr.Image(label="Peta Perbedaan Piksel Antar File (Otomatis jika mengunggah pasangan struk)", type="pil")
            with gr.TabItem("📋 Laporan Audit JSON"):
                json_view = gr.JSON(label="Struktur Data Audit Lengkap")
                downloadable = gr.File(label="Unduh Laporan Forensik JSON")

        inputs = [inp, gemma_check, deep_check]
        outputs = [
            multi_overview,
            file_selector,
            verdict_card,
            details_text,
            overlay_img,
            ela_img,
            recapture_img,
            difference_img,
            json_view,
            downloadable,
            state_store
        ]

        run_btn.click(analyze_multi_ui, inputs=inputs, outputs=outputs)
        inp.change(analyze_multi_ui, inputs=inputs, outputs=outputs)

        file_selector.change(
            on_select_file,
            inputs=[file_selector, state_store],
            outputs=[
                verdict_card,
                details_text,
                overlay_img,
                ela_img,
                recapture_img,
                json_view,
                downloadable
            ]
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

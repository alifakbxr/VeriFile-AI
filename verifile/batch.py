"""Batch forensic triage and multi-format report exporters (PDF, Excel .xlsx, CSV, JSON).

Every exported report preserves VeriFile AI's core rule: diagnostic cues and AI summaries
are review aids only, never proof of payment settlement or automatic fraud verdicts.
"""
from __future__ import annotations

import csv
import html
import io
import json
import os
import textwrap
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import pymupdf as fitz
from PIL import Image

from .forensics import UnsafeFile, analyze_file
from .gemma import Gemma4Reviewer
from .overlay import amount_crops, render_diagnostic_preview

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.pdf', '.docx'}
DEFAULT_MAX_BATCH_FILES = int(os.environ.get('BATCH_MAX_FILES', '50'))
DEFAULT_AI_MAX_FILES = int(os.environ.get('BATCH_AI_MAX_FILES', '10'))
DEFAULT_AI_DELAY_SECONDS = float(os.environ.get('BATCH_AI_DELAY_SECONDS', '1.5'))

DISCLAIMER_TEXT = (
    'Laporan triase forensik terbatas; BUKAN bukti sah transaksi bank, '
    'klasifikasi AI-generated, ataupun vonis penipuan. Validasi mutlak melalui sistem resmi bank.'
)


def collect_input_paths(inputs: Sequence[str | Path]) -> list[Path]:
    """Expand files and directories into an ordered, deduplicated list of supported paths."""
    collected: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        if not raw:
            continue
        p = Path(raw)
        if p.is_dir():
            candidates = sorted(
                item for item in p.rglob('*')
                if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS
            )
        elif p.is_file():
            candidates = [p]
        else:
            continue
        for item in candidates:
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                collected.append(item)
    return collected


def _make_thumb(image: Image.Image, max_size: tuple[int, int] = (340, 220)) -> Image.Image:
    copy = image.convert('RGB')
    copy.thumbnail(max_size)
    return copy


def analyze_batch(
    inputs: Sequence[str | Path],
    *,
    use_ai: bool = False,
    use_exiftool: bool = False,
    ai_max_files: int = DEFAULT_AI_MAX_FILES,
    ai_delay_seconds: float = DEFAULT_AI_DELAY_SECONDS,
    max_batch_files: int = DEFAULT_MAX_BATCH_FILES,
    reviewer: Gemma4Reviewer | None = None,
) -> tuple[dict[str, Any], dict[int, dict[str, Image.Image]]]:
    """Run forensic triage across multiple files, isolating per-file errors and capping AI calls."""
    paths = collect_input_paths(inputs)
    if not paths:
        raise ValueError('Tidak ada file yang didukung untuk dianalisis dalam batch.')
    safe_cap = max(1, min(int(max_batch_files), 200))
    if len(paths) > safe_cap:
        raise ValueError(f'Jumlah file ({len(paths)}) melebihi batas batch maksimal ({safe_cap} file).')

    ai_cap = max(0, int(ai_max_files))
    delay = max(0.0, float(ai_delay_seconds))
    active_reviewer = (reviewer or Gemma4Reviewer()) if use_ai else None

    items: list[dict[str, Any]] = []
    thumbnails: dict[int, dict[str, Image.Image]] = {}
    processed_count = 0
    error_count = 0
    review_count = 0
    ai_reviewed_count = 0

    for idx, path in enumerate(paths, start=1):
        safe_name = Path(path).name[:180]
        try:
            report, pages, ela = analyze_file(path, use_exiftool=use_exiftool)
            if pages:
                candidates = []
                if report['forensics'].get('overlay_diagnostics'):
                    candidates = report['forensics']['overlay_diagnostics'][0].get('amount_candidates', [])
                overlay_preview = render_diagnostic_preview(pages[0], candidates)
                thumb_entry: dict[str, Image.Image] = {
                    'original': _make_thumb(pages[0]),
                    'overlay': _make_thumb(overlay_preview),
                }
                if ela is not None:
                    thumb_entry['ela'] = _make_thumb(ela)
                thumbnails[idx] = thumb_entry

                if use_ai and active_reviewer is not None:
                    if ai_reviewed_count >= ai_cap:
                        report['gemma4'] = {
                            'status': 'skipped_batch_cap',
                            'model': None,
                            'analysis': {'summary': f'Dilewati karena batas kuota AI batch ({ai_cap} file) tercapai.'},
                        }
                    else:
                        if ai_reviewed_count > 0 and delay > 0:
                            time.sleep(delay)
                        crops = amount_crops(pages[0], candidates)
                        try:
                            report['gemma4'] = active_reviewer.review(
                                report, pages[:1] + crops[:2] if crops else pages[:3]
                            )
                            ai_reviewed_count += 1
                        except Exception as ai_exc:
                            report['gemma4'] = {
                                'status': 'error',
                                'model': active_reviewer.model_id,
                                'analysis': {'error': f'{type(ai_exc).__name__}: {ai_exc}'[:600]},
                            }
            elif use_ai:
                report['gemma4'] = {
                    'status': 'no_visual_input',
                    'model': None,
                    'analysis': {'summary': 'Dokumen tanpa pratinjau visual.'},
                }

            processed_count += 1
            if any(f.get('severity') == 'review' for f in report['forensics'].get('findings', [])):
                review_count += 1
            items.append({
                'index': idx,
                'filename': safe_name,
                'status': 'completed',
                'report': report,
                'error': None,
            })
        except (UnsafeFile, OSError, ValueError) as exc:
            error_count += 1
            items.append({
                'index': idx,
                'filename': safe_name,
                'status': 'error',
                'report': None,
                'error': str(exc)[:400],
            })

    batch_result: dict[str, Any] = {
        'schema_version': '0.4-batch',
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'totals': {
            'files_total': len(paths),
            'files_processed': processed_count,
            'files_errored': error_count,
            'needs_review_count': review_count,
            'clean_or_limited_count': max(0, processed_count - review_count),
            'ai_reviewed_count': ai_reviewed_count,
        },
        'items': items,
        'disclaimer': DISCLAIMER_TEXT,
    }
    return batch_result, thumbnails


def _sanitize_spreadsheet_text(value: Any) -> str:
    if value is None:
        return ''
    text = str(value).replace('\x00', '')
    if text and text[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + text
    return text


def _summary_row(item: dict[str, Any]) -> dict[str, Any]:
    if item['status'] != 'completed' or not item.get('report'):
        return {
            'index': item['index'],
            'filename': item['filename'],
            'status': 'error',
            'type_detected': '',
            'bytes': 0,
            'sha256': '',
            'outcome': 'Gagal diproses',
            'review_findings': 0,
            'total_findings': 0,
            'created_iso': '',
            'modified_iso': '',
            'chronology': '',
            'ocr_status': '',
            'nominal_rois': 0,
            'screen_recapture': '',
            'ai_status': '',
            'ai_model': '',
            'ai_amount': '',
            'ai_recipient': '',
            'ai_bank': '',
            'ai_summary': '',
            'error': item.get('error') or '',
        }
    rep = item['report']
    forensics = rep['forensics']
    findings = forensics.get('findings', [])
    review_cnt = sum(1 for f in findings if f.get('severity') == 'review')
    timeline = forensics.get('timeline', {})
    created = (timeline.get('created') or {}).get('normalized_iso') or ''
    modified = (timeline.get('modified') or {}).get('normalized_iso') or ''
    ocr_list = forensics.get('overlay_diagnostics', [])
    ocr_status = ocr_list[0].get('status', '') if ocr_list else 'no_visual_input'
    roi_count = sum(len(x.get('amount_candidates', [])) for x in ocr_list)
    recap_list = forensics.get('recapture_diagnostics', [])
    recap_status = recap_list[0].get('status', '') if recap_list else 'no_visual_input'

    gemma = rep.get('gemma4') or {}
    analysis = gemma.get('analysis') if isinstance(gemma.get('analysis'), dict) else {}
    tx = analysis.get('transaction_fields') if isinstance(analysis.get('transaction_fields'), dict) else {}
    ai_summary = analysis.get('summary') or analysis.get('error') or ''

    return {
        'index': item['index'],
        'filename': item['filename'],
        'status': 'completed',
        'type_detected': rep['file'].get('type_detected', ''),
        'bytes': rep['file'].get('bytes', 0),
        'sha256': rep['file'].get('sha256', ''),
        'outcome': forensics.get('summary', ''),
        'review_findings': review_cnt,
        'total_findings': len(findings),
        'created_iso': created,
        'modified_iso': modified,
        'chronology': timeline.get('chronology', ''),
        'ocr_status': ocr_status,
        'nominal_rois': roi_count,
        'screen_recapture': recap_status,
        'ai_status': gemma.get('status', 'not_run'),
        'ai_model': gemma.get('model') or '',
        'ai_amount': tx.get('amount') or '',
        'ai_recipient': tx.get('recipient') or '',
        'ai_bank': tx.get('bank') or '',
        'ai_summary': str(ai_summary)[:500],
        'error': '',
    }


SUMMARY_COLUMNS = [
    ('index', 'No'),
    ('filename', 'Filename'),
    ('status', 'Status'),
    ('type_detected', 'Type'),
    ('bytes', 'Bytes'),
    ('sha256', 'SHA-256'),
    ('outcome', 'Outcome'),
    ('review_findings', 'Review Findings'),
    ('total_findings', 'Total Findings'),
    ('created_iso', 'Created (Metadata)'),
    ('modified_iso', 'Modified (Metadata)'),
    ('chronology', 'Chronology'),
    ('ocr_status', 'OCR Status'),
    ('nominal_rois', 'Nominal ROIs'),
    ('screen_recapture', 'Screen Recapture'),
    ('ai_status', 'AI Status'),
    ('ai_model', 'AI Model'),
    ('ai_amount', 'AI Amount'),
    ('ai_recipient', 'AI Recipient'),
    ('ai_bank', 'AI Bank'),
    ('ai_summary', 'AI Summary'),
    ('error', 'Error'),
]


def export_batch_json(batch_result: dict[str, Any], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(batch_result, indent=2, ensure_ascii=False), encoding='utf-8')
    return out


def export_batch_csv(batch_result: dict[str, Any], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    keys = [k for k, _ in SUMMARY_COLUMNS]
    with out.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for item in batch_result.get('items', []):
            row = _summary_row(item)
            safe_row = {
                k: (row[k] if isinstance(row[k], int) else _sanitize_spreadsheet_text(row[k]))
                for k in keys
            }
            writer.writerow(safe_row)
    return out


def _col_letter(col_idx_one_based: int) -> str:
    letters = ''
    n = col_idx_one_based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _build_worksheet_xml(headers: list[str], rows: list[list[Any]], widths: list[int]) -> str:
    cols_xml = ''.join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths, start=1)
    )
    sheet_rows: list[str] = []

    header_cells = []
    for c_idx, h_text in enumerate(headers, start=1):
        ref = f'{_col_letter(c_idx)}1'
        escaped = html.escape(_sanitize_spreadsheet_text(h_text), quote=False)
        header_cells.append(f'<c r="{ref}" s="1" t="inlineStr"><is><t>{escaped}</t></is></c>')
    sheet_rows.append(f'<row r="1">{"".join(header_cells)}</row>')

    for r_idx, row_vals in enumerate(rows, start=2):
        cells = []
        for c_idx, val in enumerate(row_vals, start=1):
            ref = f'{_col_letter(c_idx)}{r_idx}'
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
            else:
                safe_str = _sanitize_spreadsheet_text(val)
                escaped = html.escape(safe_str, quote=False)
                cells.append(
                    f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escaped}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{r_idx}">{"".join(cells)}</row>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{"".join(sheet_rows)}</sheetData>'
        '</worksheet>'
    )


def export_batch_excel(batch_result: dict[str, Any], output_path: str | Path) -> Path:
    """Write a clean two-sheet OpenXML .xlsx workbook (Summary + Findings) without native deps."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    summary_headers = [label for _, label in SUMMARY_COLUMNS]
    summary_keys = [k for k, _ in SUMMARY_COLUMNS]
    summary_rows = []
    findings_rows = []

    for item in batch_result.get('items', []):
        s_row = _summary_row(item)
        summary_rows.append([s_row[k] for k in summary_keys])
        if item['status'] == 'completed' and item.get('report'):
            for f in item['report']['forensics'].get('findings', []):
                findings_rows.append([
                    item['index'],
                    item['filename'],
                    f.get('severity', ''),
                    f.get('code', ''),
                    f.get('source', ''),
                    f.get('title', ''),
                    f.get('detail', ''),
                ])
        elif item.get('error'):
            findings_rows.append([
                item['index'],
                item['filename'],
                'error',
                'processing_error',
                'runtime',
                'Gagal memproses berkas',
                item['error'],
            ])

    summary_widths = [6, 28, 12, 10, 12, 24, 28, 15, 14, 22, 22, 24, 16, 13, 24, 22, 18, 16, 20, 16, 42, 28]
    findings_headers = ['File No', 'Filename', 'Severity', 'Code', 'Source', 'Title', 'Detail']
    findings_widths = [8, 28, 12, 24, 16, 30, 60]

    sheet1_xml = _build_worksheet_xml(summary_headers, summary_rows, summary_widths)
    sheet2_xml = _build_worksheet_xml(findings_headers, findings_rows, findings_widths)

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/worksheets/sheet2.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets>'
        '<sheet name="Summary" sheetId="1" r:id="rId1"/>'
        '<sheet name="Findings" sheetId="2" r:id="rId2"/>'
        '</sheets>'
        '</workbook>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet2.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        '</Relationships>'
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="10"/><name val="Calibri"/></font>'
        '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1B365D"/></patternFill></fill>'
        '</fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '</cellXfs>'
        '</styleSheet>'
    )

    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', root_rels)
        zf.writestr('xl/workbook.xml', workbook_xml)
        zf.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        zf.writestr('xl/styles.xml', styles_xml)
        zf.writestr('xl/worksheets/sheet1.xml', sheet1_xml)
        zf.writestr('xl/worksheets/sheet2.xml', sheet2_xml)
    return out


def _pdf_safe(value: Any) -> str:
    text = str(value or '')
    replacements = {
        '•': '-', '→': '->', '—': '-', '–': '-',
        '“': '"', '”': '"', '‘': "'", '’': "'", '🔎': '',
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode('latin-1', errors='replace').decode('latin-1')


def _draw_wrapped_lines(
    doc: fitz.Document,
    page: fitz.Page,
    x: float,
    y: float,
    text: str,
    *,
    width_chars: int = 92,
    fontsize: float = 9.0,
    line_height: float = 12.5,
    fontname: str = 'helv',
    color: tuple[float, float, float] = (0.12, 0.16, 0.22),
) -> tuple[fitz.Page, float]:
    clean = _pdf_safe(text)
    paragraphs = clean.splitlines() or ['']
    for para in paragraphs:
        wrapped = textwrap.wrap(para, width=width_chars) or ['']
        for line in wrapped:
            if y > 795:
                page = doc.new_page(width=595, height=842)
                y = 45.0
            page.insert_text((x, y), line, fontsize=fontsize, fontname=fontname, color=color)
            y += line_height
    return page, y


def export_batch_pdf(
    batch_result: dict[str, Any],
    output_path: str | Path,
    thumbnails: dict[int, dict[str, Image.Image]] | None = None,
) -> Path:
    """Render an A4 multi-page PDF batch audit report with summary table and visual thumbnails."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    thumbs = thumbnails or {}

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    # Top banner
    page.draw_rect(fitz.Rect(0, 0, 595, 76), color=None, fill=(0.11, 0.21, 0.36))
    page.insert_text((34, 34), 'VeriFile AI - Batch Forensic Triage Report',
                     fontsize=16, fontname='hebo', color=(1, 1, 1))
    gen_time = _pdf_safe(batch_result.get('generated_at_utc', ''))
    page.insert_text((34, 54), f'Generated (UTC): {gen_time}  |  Schema: {batch_result.get("schema_version", "")}',
                     fontsize=9, fontname='helv', color=(0.82, 0.88, 0.96))

    # Disclaimer box
    page.draw_rect(fitz.Rect(34, 88, 561, 128), color=(0.85, 0.62, 0.20),
                   fill=(1.0, 0.97, 0.90), width=0.8)
    page, _ = _draw_wrapped_lines(
        doc, page, 42, 103,
        'PENTING: ' + batch_result.get('disclaimer', DISCLAIMER_TEXT),
        width_chars=90, fontsize=8.5, line_height=11.5, color=(0.42, 0.26, 0.04)
    )

    # Stats bar
    totals = batch_result.get('totals', {})
    stats_items = [
        ('Total Berkas', str(totals.get('files_total', 0))),
        ('Berhasil Dianalisis', str(totals.get('files_processed', 0))),
        ('Perlu Pemeriksaan', str(totals.get('needs_review_count', 0))),
        ('Gagal / Error', str(totals.get('files_errored', 0))),
        ('Direview AI', str(totals.get('ai_reviewed_count', 0))),
    ]
    box_w = (561 - 34) / len(stats_items)
    for idx, (label, val) in enumerate(stats_items):
        x0 = 34 + idx * box_w
        page.draw_rect(fitz.Rect(x0 + 2, 138, x0 + box_w - 2, 182),
                       color=(0.82, 0.86, 0.91), fill=(0.96, 0.98, 1.0), width=0.7)
        page.insert_text((x0 + 10, 158), val, fontsize=14, fontname='hebo', color=(0.11, 0.21, 0.36))
        page.insert_text((x0 + 10, 173), _pdf_safe(label), fontsize=7.5, fontname='helv', color=(0.35, 0.40, 0.48))

    # Summary Table
    y = 204.0
    page.insert_text((34, y), 'Ringkasan Batch', fontsize=12, fontname='hebo', color=(0.11, 0.21, 0.36))
    y += 12.0
    page.draw_rect(fitz.Rect(34, y, 561, y + 20), color=None, fill=(0.18, 0.30, 0.47))
    col_x = [38, 64, 220, 265, 395, 458]
    for cx, title in zip(col_x, ['#', 'Nama Berkas', 'Tipe', 'Hasil Triase', 'Temuan', 'Status AI']):
        page.insert_text((cx, y + 13.5), title, fontsize=8, fontname='hebo', color=(1, 1, 1))
    y += 20.0

    for row_i, item in enumerate(batch_result.get('items', [])):
        if y > 780:
            page = doc.new_page(width=595, height=842)
            y = 45.0
        s = _summary_row(item)
        bg = (0.97, 0.98, 0.99) if row_i % 2 == 0 else (1.0, 1.0, 1.0)
        page.draw_rect(fitz.Rect(34, y, 561, y + 18), color=(0.88, 0.90, 0.93), fill=bg, width=0.4)
        outcome_short = s['outcome'][:26]
        findings_str = f"{s['review_findings']} rev / {s['total_findings']} tot" if s['status'] == 'completed' else 'ERR'
        vals = [
            str(s['index']),
            s['filename'][:27],
            (s['type_detected'] or '-').upper()[:6],
            outcome_short,
            findings_str,
            (s['ai_status'] or '-')[:18],
        ]
        outcome_color = (
            (0.68, 0.14, 0.14) if s['status'] == 'error'
            else (0.62, 0.36, 0.02) if s['review_findings'] > 0
            else (0.14, 0.42, 0.22)
        )
        for c_i, (cx, v) in enumerate(zip(col_x, vals)):
            clr = outcome_color if c_i == 3 else (0.15, 0.18, 0.22)
            page.insert_text((cx, y + 12.5), _pdf_safe(v), fontsize=7.8, fontname='helv', color=clr)
        y += 18.0

    # Detailed Per-File Pages
    for item in batch_result.get('items', []):
        page = doc.new_page(width=595, height=842)
        y = 42.0
        idx = item['index']
        fname = _pdf_safe(item['filename'])
        is_err = item['status'] != 'completed' or not item.get('report')

        banner_fill = (0.65, 0.16, 0.16) if is_err else (0.14, 0.26, 0.44)
        page.draw_rect(fitz.Rect(34, y - 16, 561, y + 12), color=None, fill=banner_fill)
        page.insert_text((42, y + 2), f'[{idx}] {fname}', fontsize=11, fontname='hebo', color=(1, 1, 1))
        y += 26.0

        if is_err:
            page, y = _draw_wrapped_lines(
                doc, page, 38, y,
                f"Status: GAGAL DIPROSES\nDetail Error: {item.get('error') or 'Unknown error'}",
                width_chars=88, fontsize=9.5, color=(0.60, 0.12, 0.12),
            )
            continue

        rep = item['report']
        f_info = rep['file']
        forensics = rep['forensics']
        timeline = forensics.get('timeline', {})
        created_str = (timeline.get('created') or {}).get('normalized_iso') or 'tidak tersedia'
        modified_str = (timeline.get('modified') or {}).get('normalized_iso') or 'tidak tersedia'

        meta_lines = (
            f"Hasil Triase: {forensics.get('summary', '')}\n"
            f"Tipe Terdeteksi: {f_info.get('type_detected', '')}  |  Ukuran: {f_info.get('bytes', 0):,} bytes\n"
            f"SHA-256: {f_info.get('sha256', '')}\n"
            f"Dibuat (metadata): {created_str}  |  Diedit (metadata): {modified_str}\n"
            f"Kronologi Metadata: {timeline.get('chronology', '')}"
        )
        page, y = _draw_wrapped_lines(doc, page, 38, y, meta_lines, width_chars=92, fontsize=8.8, line_height=12.5)
        y += 6.0

        # Embed side-by-side thumbnails when available
        item_thumbs = thumbs.get(idx)
        if item_thumbs and ('original' in item_thumbs or 'overlay' in item_thumbs):
            if y + 165 > 790:
                page = doc.new_page(width=595, height=842)
                y = 45.0
            slots = [
                ('original', 'Pratinjau Dokumen', 38.0),
                ('overlay', 'Diagnostik Tekstur + ROI Nominal (Bukan Skor Fraud)', 304.0),
            ]
            for key, caption, x_left in slots:
                pil_im = item_thumbs.get(key)
                if pil_im is None:
                    continue
                buf = io.BytesIO()
                pil_im.save(buf, format='PNG')
                img_rect = fitz.Rect(x_left, y + 12, x_left + 250, y + 152)
                page.draw_rect(img_rect, color=(0.80, 0.84, 0.89), fill=(0.98, 0.98, 0.99), width=0.6)
                page.insert_image(img_rect, stream=buf.getvalue(), keep_proportion=True)
                page.insert_text((x_left, y + 8), caption, fontsize=7.8, fontname='hebo', color=(0.25, 0.30, 0.38))
            y += 166.0

        # Findings list
        page.insert_text((38, y), 'Indikator & Temuan Forensik:', fontsize=10, fontname='hebo', color=(0.11, 0.21, 0.36))
        y += 14.0
        findings = forensics.get('findings', [])
        if not findings:
            page, y = _draw_wrapped_lines(doc, page, 44, y, '- Tidak ada temuan dari pemeriksaan terbatas.', fontsize=8.8)
        else:
            for f in findings:
                sev = f.get('severity', 'info').upper()
                f_color = (0.58, 0.28, 0.02) if sev == 'REVIEW' else (0.18, 0.22, 0.28)
                line = f"- [{sev}] {f.get('title', '')} ({f.get('code', '')}): {f.get('detail', '')}"
                page, y = _draw_wrapped_lines(doc, page, 44, y, line, width_chars=88, fontsize=8.6, line_height=11.8, color=f_color)
                y += 2.0

        # AI section
        gemma = rep.get('gemma4') or {}
        if gemma.get('status') and gemma.get('status') != 'not_run':
            y += 6.0
            page.insert_text(
                (38, y),
                _pdf_safe(f"Review AI Multimodal ({gemma.get('status')} - {gemma.get('model') or 'n/a'}):"),
                fontsize=10, fontname='hebo', color=(0.11, 0.21, 0.36),
            )
            y += 14.0
            analysis = gemma.get('analysis') if isinstance(gemma.get('analysis'), dict) else {}
            tx = analysis.get('transaction_fields') if isinstance(analysis.get('transaction_fields'), dict) else {}
            if tx:
                tx_parts = [f"{k}: {v}" for k, v in tx.items() if v]
                if tx_parts:
                    page, y = _draw_wrapped_lines(
                        doc, page, 44, y,
                        'Field Terbaca: ' + ' | '.join(tx_parts),
                        width_chars=88, fontsize=8.5, color=(0.15, 0.32, 0.22),
                    )
            ai_sum = analysis.get('summary') or analysis.get('error') or analysis.get('unstructured_model_output') or ''
            if ai_sum:
                page, y = _draw_wrapped_lines(doc, page, 44, y, f'Ringkasan: {ai_sum}', width_chars=88, fontsize=8.6)

    doc.save(out)
    doc.close()
    return out


def format_batch_markdown(batch_result: dict[str, Any]) -> str:
    """Build a concise GitHub-flavored Markdown summary table for the Gradio UI."""
    t = batch_result.get('totals', {})
    lines = [
        f"### Hasil Batch: {t.get('files_processed', 0)}/{t.get('files_total', 0)} berkas dianalisis",
        (
            f"**Perlu pemeriksaan lanjutan:** `{t.get('needs_review_count', 0)}` · "
            f"**Indikator terbatas/info:** `{t.get('clean_or_limited_count', 0)}` · "
            f"**Gagal/Error:** `{t.get('files_errored', 0)}` · "
            f"**Direview AI:** `{t.get('ai_reviewed_count', 0)}`"
        ),
        '',
        '| # | Berkas | Tipe | Hasil Triase | Temuan (Review/Total) | Status AI |',
        '| --- | --- | --- | --- | --- | --- |',
    ]
    for item in batch_result.get('items', []):
        s = _summary_row(item)
        safe_name = s['filename'].replace('|', '\\|')
        if s['status'] != 'completed':
            err = (s['error'] or 'Error').replace('|', '\\|')
            lines.append(f"| {s['index']} | `{safe_name}` | - | **Gagal:** {err} | - | - |")
        else:
            lines.append(
                f"| {s['index']} | `{safe_name}` | `{s['type_detected']}` | {s['outcome']} | "
                f"`{s['review_findings']}/{s['total_findings']}` | `{s['ai_status']}` |"
            )
    lines.append(f"\n> {batch_result.get('disclaimer', DISCLAIMER_TEXT)}")
    return '\n'.join(lines)


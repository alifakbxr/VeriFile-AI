import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pymupdf as fitz
from PIL import Image, ImageDraw

from verifile.batch import (
    analyze_batch,
    collect_input_paths,
    export_batch_csv,
    export_batch_excel,
    export_batch_json,
    export_batch_pdf,
)
from verifile.gemma import Gemma4Reviewer


def _create_sample_files(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    img1 = folder / 'receipt_clean.png'
    im = Image.new('RGB', (320, 200), '#ffffff')
    dr = ImageDraw.Draw(im)
    dr.text((20, 40), 'Nominal Rp 150.000', fill='#111111')
    im.save(img1, format='PNG')

    pdf1 = folder / 'edited_receipt.pdf'
    doc = fitz.open()
    page = doc.new_page(width=400, height=260)
    page.insert_text((50, 100), 'Total Rp 100.000', fontsize=16)
    page.draw_rect(fitz.Rect(45, 82, 260, 110), color=None, fill=(1, 1, 1))
    page.insert_text((50, 100), 'Total Rp 900.000', fontsize=16)
    doc.save(pdf1)
    doc.close()

    bad = folder / 'corrupt.jpg'
    bad.write_bytes(b'not-a-valid-image')
    return [img1, pdf1, bad]


def test_collect_input_paths_expands_directories_and_filters_extensions(tmp_path):
    files = _create_sample_files(tmp_path / 'samples')
    (tmp_path / 'samples' / 'notes.txt').write_text('ignore me', encoding='utf-8')

    collected = collect_input_paths([tmp_path / 'samples'])
    names = [p.name for p in collected]
    assert 'receipt_clean.png' in names
    assert 'edited_receipt.pdf' in names
    assert 'corrupt.jpg' in names
    assert 'notes.txt' not in names


def test_analyze_batch_isolates_errors_and_enforces_ai_cap(monkeypatch, tmp_path):
    monkeypatch.setenv('GEMINI_API_KEY', 'batch-key')
    monkeypatch.setenv('GEMINI_ONLY', '1')
    files = _create_sample_files(tmp_path / 'batch')

    ai_calls = 0

    def fake_gemini(**kwargs):
        nonlocal ai_calls
        ai_calls += 1
        return '{"summary": "AI batch ok", "transaction_fields": {"amount": "Rp 150.000"}}'

    reviewer = Gemma4Reviewer(gemini_caller=fake_gemini)

    batch_result, thumbs = analyze_batch(
        files,
        use_ai=True,
        ai_max_files=1,
        ai_delay_seconds=0.0,
        reviewer=reviewer,
    )

    assert batch_result['totals']['files_total'] == 3
    assert batch_result['totals']['files_processed'] == 2
    assert batch_result['totals']['files_errored'] == 1
    assert batch_result['totals']['needs_review_count'] >= 1
    assert batch_result['totals']['ai_reviewed_count'] == 1
    assert ai_calls == 1

    statuses = [item['status'] for item in batch_result['items']]
    assert statuses == ['completed', 'completed', 'error']
    assert batch_result['items'][0]['report']['gemma4']['status'] == 'completed_gemini_api'
    assert batch_result['items'][1]['report']['gemma4']['status'] == 'skipped_batch_cap'
    assert 1 in thumbs


def test_export_batch_pdf_generates_readable_multipage_report_with_thumbnails(tmp_path):
    files = _create_sample_files(tmp_path / 'pdf_in')
    batch_result, thumbs = analyze_batch(files, use_ai=False)

    out_pdf = tmp_path / 'out' / 'batch_report.pdf'
    saved = export_batch_pdf(batch_result, out_pdf, thumbnails=thumbs)

    assert saved == out_pdf
    assert out_pdf.is_file() and out_pdf.stat().st_size > 1000

    with fitz.open(out_pdf) as doc:
        assert doc.page_count >= 2
        full_text = '\n'.join(doc.load_page(i).get_text('text') for i in range(doc.page_count))
        assert 'VeriFile AI' in full_text
        assert 'receipt_clean.png' in full_text
        assert 'edited_receipt.pdf' in full_text
        assert 'corrupt.jpg' in full_text
        assert 'pdf_text_cover_replace' in full_text or 'Pola teks tertutup' in full_text
        total_images = sum(len(doc.load_page(i).get_images()) for i in range(doc.page_count))
        assert total_images >= 2


def test_export_batch_excel_creates_valid_xlsx_with_summary_and_findings_sheets(tmp_path):
    files = _create_sample_files(tmp_path / 'xlsx_in')
    # Include a formula-like filename to verify spreadsheet injection sanitization
    tricky = tmp_path / 'xlsx_in' / '=cmd_test.png'
    Image.new('RGB', (60, 60), 'white').save(tricky, format='PNG')
    batch_result, _ = analyze_batch([*files, tricky], use_ai=False)

    out_xlsx = tmp_path / 'out' / 'batch_report.xlsx'
    saved = export_batch_excel(batch_result, out_xlsx)

    assert saved == out_xlsx
    assert out_xlsx.is_file()
    with zipfile.ZipFile(out_xlsx, 'r') as zf:
        names = set(zf.namelist())
        assert 'xl/workbook.xml' in names
        assert 'xl/worksheets/sheet1.xml' in names
        assert 'xl/worksheets/sheet2.xml' in names
        wb_xml = ET.fromstring(zf.read('xl/workbook.xml'))
        sheet_names = [el.attrib.get('name') for el in wb_xml.iter() if el.tag.endswith('sheet')]
        assert 'Summary' in sheet_names
        assert 'Findings' in sheet_names
        sheet1_raw = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')
        assert "'=cmd_test.png" in sheet1_raw


def test_export_batch_csv_and_json(tmp_path):
    files = _create_sample_files(tmp_path / 'csv_in')
    batch_result, _ = analyze_batch(files, use_ai=False)

    out_csv = export_batch_csv(batch_result, tmp_path / 'report.csv')
    out_json = export_batch_json(batch_result, tmp_path / 'report.json')

    rows = list(csv.DictReader(io.StringIO(out_csv.read_text(encoding='utf-8-sig'))))
    assert len(rows) == 3
    assert rows[0]['filename'] == 'receipt_clean.png'
    assert rows[2]['status'] == 'error'

    parsed = json.loads(out_json.read_text(encoding='utf-8'))
    assert parsed['totals']['files_total'] == 3


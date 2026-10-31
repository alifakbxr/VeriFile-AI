import io
from pathlib import Path
from zipfile import ZipFile

import pymupdf as fitz
import pytest
from PIL import Image

from verifile.forensics import UnsafeFile, analyze_bytes, detect_type
from verifile.gemma import _json_or_raw


def png():
    buffer = io.BytesIO()
    Image.new('RGB', (48, 40), '#ffffff').save(buffer, format='PNG')
    return buffer.getvalue()


def test_png_triage_has_hash_and_image():
    report, pages, ela = analyze_bytes(png(), 'receipt.png')
    assert report['file']['type_detected'] == 'png'
    assert len(report['file']['sha256']) == 64
    assert len(pages) == 1
    assert ela is None
    assert report['gemma4']['status'] == 'not_run'
    assert 'TIDAK DAPAT DIVERIFIKASI' in report['verdict']


def test_signature_mismatch_flagged():
    report, _, _ = analyze_bytes(png(), 'receipt.jpg')
    assert any(f['code'] == 'extension_mismatch' for f in report['forensics']['findings'])


def test_unknown_or_oversized_rejected():
    with pytest.raises(UnsafeFile):
        analyze_bytes(b'hello', 'x.txt')
    with pytest.raises(UnsafeFile):
        analyze_bytes(b'X' * (20 * 1024 * 1024 + 1), 'huge.png')


def test_pdf_triage():
    d = fitz.open()
    p = d.new_page(width=300, height=200)
    p.insert_text((50, 80), 'CONTOH TRANSFER')
    content = d.tobytes()
    d.close()
    report, pages, _ = analyze_bytes(content, 'sample.pdf')
    assert report['forensics']['metadata']['pages'][0]['selectable_text'].strip() == 'CONTOH TRANSFER'
    assert len(pages) == 1


def test_docx_core_metadata():
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<w:document xmlns:w="urn:word"><w:t>TRANSFER DEMO</w:t></w:document>')
        z.writestr('docProps/core.xml', '<cp:coreProperties xmlns:cp="x" xmlns:dc="y"><dc:creator>Tester</dc:creator></cp:coreProperties>')
    report, pages, _ = analyze_bytes(stream.getvalue(), 'doc.docx')
    assert report['forensics']['metadata']['core_properties']['creator'] == 'Tester'
    assert 'TRANSFER DEMO' in report['forensics']['metadata']['text_preview']
    assert pages == []


def test_ai_parser_nonjson_is_not_fabricated():
    assert 'unstructured_model_output' in _json_or_raw('AI thinks something')
    assert _json_or_raw('{"summary": "belum pasti"}')['summary'] == 'belum pasti'


def test_pdf_oversized_dimensions_rejected():
    d = fitz.open()
    d.new_page(width=6000, height=6000)
    content = d.tobytes()
    d.close()
    with pytest.raises(UnsafeFile, match='di luar batas aman'):
        analyze_bytes(content, 'huge_dim.pdf')


def test_pdf_pii_account_masked():
    d = fitz.open()
    p = d.new_page(width=300, height=200)
    p.insert_text((50, 80), 'Rekening: 123456789012')
    content = d.tobytes()
    d.close()
    report, _, _ = analyze_bytes(content, 'masked.pdf')
    text = report['forensics']['metadata']['pages'][0]['selectable_text']
    assert '123456789012' not in text
    assert '********9012' in text


def test_docx_entity_dtd_rejected():
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<!DOCTYPE test [<!ENTITY xxe "evil">]><w:document xmlns:w="urn:word"><w:t>&xxe;</w:t></w:document>')
    with pytest.raises(UnsafeFile, match='entitas/DTD'):
        analyze_bytes(stream.getvalue(), 'xxe.docx')


def test_docx_pii_account_masked():
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types/>')
        z.writestr('word/document.xml', '<w:document xmlns:w="urn:word"><w:t>Transfer ke 555123456789 Sukses</w:t></w:document>')
    report, _, _ = analyze_bytes(stream.getvalue(), 'doc.docx')
    preview = report['forensics']['metadata']['text_preview']
    assert '555123456789' not in preview
    assert '********6789' in preview


def test_generative_ai_c2pa_detected():
    # Synthetic JPEG with C2PA manifest marker
    buf = io.BytesIO()
    img = Image.new('RGB', (100, 100), color='#ffffff')
    img.save(buf, format='JPEG')
    raw = buf.getvalue() + b' urn:c2pa:test-manifest Google Generative AI SynthID '
    report, _, _ = analyze_bytes(raw, 'synthetic_ai.jpg')
    assert report['verdict_category'] == 'MANIPULASI_TERDETEKSI'
    assert report['risk_level'] == 'TINGGI'
    assert any(f['code'] == 'generative_ai_provenance' for f in report['forensics']['findings'])


def test_demo_receipt_files_if_present():
    orig_path = Path('demo/TEST DATA/202610300859170551-1793419781221.jpg')
    fake_path = Path('demo/TEST DATA/202610300859170551-179341978122122.jpg')
    if orig_path.exists() and fake_path.exists():
        from verifile.forensics import analyze_file
        orig_res, _, _ = analyze_file(orig_path)
        fake_res, _, _ = analyze_file(fake_path)

        assert orig_res['verdict_category'] == 'TIDAK_TERDETEKSI_ANOMALI'
        assert orig_res['risk_level'] == 'RENDAH'
        assert orig_res['receipt_data']['bank'] == 'wondr by BNI'

        assert fake_res['verdict_category'] == 'MANIPULASI_TERDETEKSI'
        assert fake_res['risk_level'] == 'TINGGI'
        assert 'REKAYASA' in fake_res['verdict_title']


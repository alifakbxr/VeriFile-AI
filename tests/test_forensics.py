import io
from zipfile import ZipFile

import fitz
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

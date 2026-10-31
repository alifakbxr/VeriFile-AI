"""Tests for creation/modification timestamp evidence and non-claims."""
import io
import os
import struct
import zlib
from zipfile import ZipFile

import pymupdf as fitz
from PIL import Image, PngImagePlugin

from verifile.forensics import analyze_bytes, analyze_file
from verifile.timeline import parse_timestamp, extract_png_time


def test_date_parser_supported_formats_and_timezone_safety():
    assert parse_timestamp('2026:10:31 10:30:00')[0] == '2026-10-31T10:30:00'
    assert parse_timestamp('2026:10:31 10:30:00+07:00') == ('2026-10-31T10:30:00+07:00', True)
    assert parse_timestamp("D:20261031103000+07'00'") == ('2026-10-31T10:30:00+07:00', True)
    assert parse_timestamp('2026-10-31T10:30:00Z') == ('2026-10-31T10:30:00+00:00', True)
    assert parse_timestamp('0000:00:00 00:00:00')[0] is None


def test_pdf_info_dates_and_editor_in_timeline():
    d = fitz.open()
    d.new_page().insert_text((40,40),'Test')
    d.set_metadata({'author': 'Demo Author', 'creator': 'DocCreator',
                    'creationDate': "D:20261031090000+07'00'",
                    'modDate': "D:20261031103000+07'00'"})
    raw = d.tobytes()
    d.close()
    report, *_ = analyze_bytes(raw, 'demo.pdf')
    timeline = report['forensics']['timeline']
    assert timeline['created']['normalized_iso'] == '2026-10-31T09:00:00+07:00'
    assert timeline['modified']['normalized_iso'] == '2026-10-31T10:30:00+07:00'
    assert timeline['chronology'] == 'modification_on_or_after_creation_recorded'
    assert report['forensics']['metadata']['document_metadata']['author'] == 'Demo Author'


def test_docx_inconsistent_dates_not_pretended_proof_of_fraud():
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as zipfile:
        zipfile.writestr('[Content_Types].xml','<Types/>')
        zipfile.writestr('word/document.xml', '<w:document xmlns:w="urn:word"><w:t>OK</w:t></w:document>')
        zipfile.writestr('docProps/core.xml', '''<cp:coreProperties xmlns:cp="urn:cp" xmlns:dc="urn:dc" xmlns:dcterms="urn:dcterms">
          <dc:creator>Test Creator</dc:creator><cp:lastModifiedBy>Test Editor</cp:lastModifiedBy>
          <dcterms:created>2026-10-31T15:00:00Z</dcterms:created>
          <dcterms:modified>2026-10-31T10:00:00Z</dcterms:modified>
        </cp:coreProperties>''')
    report, *_ = analyze_bytes(stream.getvalue(), 'demo.docx')
    timeline = report['forensics']['timeline']
    assert timeline['created']['source'] == 'docx.core.created'
    assert timeline['modified']['source'] == 'docx.core.modified'
    assert timeline['chronology'] == 'metadata_timestamp_order_conflict'
    assert any(f['code'] == 'metadata_timestamp_order_conflict' and f['severity']=='review'
               for f in report['forensics']['findings'])
    assert 'TIDAK DAPAT DIVERIFIKASI' in report['verdict']
    assert 'docProps/core.xml' in report['forensics']['metadata']['zip_entry_times_unverified']


def test_png_text_and_xmp_extracted():
    buffer = io.BytesIO()
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text('Creation Time', '2026-10-31T09:00:00+07:00')
    pnginfo.add_itxt('XML:com.adobe.xmp', '''<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:xmp="http://ns.adobe.com/xap/1.0/">
      <rdf:RDF><rdf:Description xmp:CreateDate="2026-10-31T09:00:00+07:00" xmp:ModifyDate="2026-10-31T11:00:00+07:00" xmp:CreatorTool="Example Editor"/></rdf:RDF>
    </x:xmpmeta>''')
    Image.new('RGB',(70,60),'white').save(buffer, 'PNG', pnginfo=pnginfo)
    report, *_ = analyze_bytes(buffer.getvalue(), 'demo.png')
    timeline = report['forensics']['timeline']
    assert timeline['created']['source'] == 'png.Creation Time'
    assert timeline['modified']['source'] == 'xmp.ModifyDate'
    assert report['forensics']['metadata']['xmp_selected']['CreatorTool']=='Example Editor'


def test_png_time_is_modified_not_creation():
    b = io.BytesIO()
    Image.new('RGB',(40,30),'white').save(b, 'PNG')
    raw=b.getvalue()
    t = b'tIME' + struct.pack('>HBBBBB', 2026, 10, 31, 14, 15, 16)
    chunk = struct.pack('>I',7)+t+struct.pack('>I',zlib.crc32(t)&0xffffffff)
    raw=raw[:-12]+chunk+raw[-12:]
    assert extract_png_time(raw) == '2026-10-31T14:15:16+00:00'
    report, *_ = analyze_bytes(raw, 'time.png')
    timeline = report['forensics']['timeline']
    assert timeline['created'] is None
    assert timeline['modified']['source'] == 'png.tIME'


def test_observed_fs_time_not_assumed_original_creation(tmp_path):
    b = io.BytesIO()
    Image.new('RGB', (32,32), 'white').save(b, 'PNG')
    path = tmp_path/'copied.png'
    path.write_bytes(b.getvalue())
    report, *_ = analyze_file(path)
    fs=report['file']['observed_filesystem']
    assert fs['observed_modified_utc']
    assert fs['trust'] == 'current_runtime_filesystem_only'
    assert 'inode change time bukan tanggal pembuatan' in fs['warning']
    assert report['forensics']['timeline']['created'] is None

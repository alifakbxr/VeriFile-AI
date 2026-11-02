import json
import sys
from pathlib import Path

from PIL import Image

from verifile import cli


def test_cli_single_file_json_stays_backward_compatible(monkeypatch, tmp_path):
    img = tmp_path / 'one.png'
    Image.new('RGB', (80, 60), '#ffffff').save(img, format='PNG')
    out_json = tmp_path / 'single.json'

    monkeypatch.setattr(sys, 'argv', ['verifile.cli', str(img), '--output', str(out_json)])
    cli.main()

    data = json.loads(out_json.read_text(encoding='utf-8'))
    assert data['schema_version'] in {'0.4', '0.5'}
    assert data['file']['type_detected'] == 'png'


def test_cli_directory_batch_exports_pdf_and_xlsx(monkeypatch, tmp_path):
    in_dir = tmp_path / 'folder'
    in_dir.mkdir()
    Image.new('RGB', (90, 70), '#ffffff').save(in_dir / 'a.png', format='PNG')
    Image.new('RGB', (90, 70), '#eeeeee').save(in_dir / 'b.jpg', format='JPEG')

    out_pdf = tmp_path / 'report.pdf'
    monkeypatch.setattr(sys, 'argv', ['verifile.cli', str(in_dir), '--output', str(out_pdf)])
    cli.main()
    assert out_pdf.is_file() and out_pdf.stat().st_size > 800

    out_xlsx = tmp_path / 'report.xlsx'
    monkeypatch.setattr(sys, 'argv', ['verifile.cli', str(in_dir), '--output', str(out_xlsx)])
    cli.main()
    assert out_xlsx.is_file() and out_xlsx.stat().st_size > 500


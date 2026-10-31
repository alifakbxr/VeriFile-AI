import io

import fitz
import numpy as np
from PIL import Image, ImageDraw

from verifile.forensics import analyze_bytes
from verifile.overlay import compare_with_reference, inspect_amount_overlay


def synthetic_pair():
    original = Image.new('RGB', (500, 250), '#eeeeee')
    dr = ImageDraw.Draw(original)
    dr.text((60, 96), 'Total Rp 120.000', fill='#111111')
    altered = original.copy()
    dr = ImageDraw.Draw(altered)
    dr.rectangle((55,90,260,120),fill='#eeeeee')
    dr.text((60,96),'Total Rp 920.000',fill='#111111')
    return original,altered


def test_amount_roi_and_heatmap_with_injected_ocr():
    original, altered = synthetic_pair()
    roi = {'bbox':[55,90,225,117], 'text':'Total Rp 920.000','confidence':0.98}
    result, heatmap, crops = inspect_amount_overlay(altered, [roi])
    assert result['status'] == 'injected_for_test'
    assert len(result['amount_candidates']) == 1
    assert result['amount_candidates'][0]['texture_diagnostic']['status'] == 'computed'
    assert heatmap.size == altered.size
    assert len(crops) == 1
    assert 'bukti' in result['interpretation'].lower() or 'bukti' in ' '.join(result['limitations']).lower() or 'dapat dipastikan' in result['interpretation']


def test_exact_reference_localizes_changed_amount():
    original, altered = synthetic_pair()
    report, preview = compare_with_reference(altered, original)
    assert report['status'] == 'completed'
    assert len(report['changed_regions']) >= 1
    assert preview is not None
    x0,y0,x1,y1 = report['changed_regions'][0]['bbox']
    assert x0 <= 200 and y0 < 130 and x1 > 90 and y1 >= 95
    assert report['changed_pixel_fraction'] < 0.1


def test_reference_of_different_resolution_refused():
    original, altered = synthetic_pair()
    report, _ = compare_with_reference(altered, original.resize((250,125)))
    assert report['status'] == 'incompatible_dimensions'


def test_pdf_text_painted_over_then_replaced_detected():
    pdf = fitz.open()
    page = pdf.new_page(width=450,height=300)
    page.insert_text((70,120),'Total Rp 120.000',fontsize=18)
    page.draw_rect(fitz.Rect(65,100,290,130),color=None,fill=(1,1,1))
    page.insert_text((70,120),'Total Rp 920.000',fontsize=18)
    raw = pdf.tobytes()
    pdf.close()
    report, *_ = analyze_bytes(raw, 'sample.pdf')
    assert any(f['code'] == 'pdf_text_cover_replace' for f in report['forensics']['findings'])
    regions = report['forensics']['metadata']['pages'][0]['text_cover_and_replace_candidates']
    assert len(regions) > 0


def test_clean_pdf_does_not_flag_cover_and_replace():
    pdf=fitz.open()
    page=pdf.new_page(width=450,height=300)
    page.insert_text((70,120),'Total Rp 120.000',fontsize=18)
    raw=pdf.tobytes()
    pdf.close()
    report, *_=analyze_bytes(raw,'clean.pdf')
    assert not any(f['code']=='pdf_text_cover_replace' for f in report['forensics']['findings'])

"""Targeted amount-overlay *triage*. The visualizations are NOT proof of manipulation.

RapidOCR is optional; OpenCV visualization and reference comparison run without OCR.
Only local input bytes are processed; no uploads to external services.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

AMOUNT_PATTERN = re.compile(r'(?:\b(?:rp|idr)\b\s*\.?\s*)?[\d][\d.,\s]{2,}', re.I)
MAX_DIM = 1600


def _image_array(image: Image.Image) -> np.ndarray:
    im = image.convert('RGB')
    im.thumbnail((MAX_DIM, MAX_DIM))
    return np.array(im)


def _bbox_from_points(points: Any, width: int, height: int) -> list[int] | None:
    try:
        p = np.asarray(points, dtype=float).reshape(-1, 2)
        if p.size < 4 or not np.isfinite(p).all():
            return None
        x0, y0 = np.min(p, axis=0)
        x1, y1 = np.max(p, axis=0)
        b = [max(0, int(x0)), max(0, int(y0)), min(width, int(np.ceil(x1))), min(height, int(np.ceil(y1)))]
        return b if b[2] - b[0] >= 4 and b[3] - b[1] >= 4 else None
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=1)
def _get_rapidocr_engine():
    from rapidocr import RapidOCR
    return RapidOCR()


def extract_ocr_lines(image: Image.Image) -> tuple[list[dict], str]:
    """RapidOCR 3.x documented result.boxes/txts/scores interface.

    OCR is intentionally optional: the local forensic tool never silently claims
    that OCR ran when its dependency is absent or the engine errors.
    """
    try:
        engine = _get_rapidocr_engine()
    except ImportError:
        return [], 'not_installed (pip install -r requirements-ocr.txt)'
    try:
        arr = _image_array(image)
        # PIL is accepted by RapidOCR and avoids its ndarray BGR/RGB distinction.
        result = engine(Image.fromarray(arr))
        if result is None or getattr(result, 'boxes', None) is None:
            return [], 'completed_no_text'
        rows = []
        scores = result.scores if result.scores is not None else []
        for coords, raw, score in zip(result.boxes, result.txts or [], scores):
            box = _bbox_from_points(coords, arr.shape[1], arr.shape[0])
            if box is None:
                continue
            rows.append({'bbox': box, 'text': str(raw)[:120], 'confidence': round(float(score), 3)})
        return rows[:100], 'completed'
    except Exception as exc:
        return [], f'error: {type(exc).__name__}: {str(exc)[:160]}'


def _redact(text: str) -> str:
    # Do not publish full bank accounts or card numbers in diagnostic JSON.
    return re.sub(r'(?<!\d)\d{9,20}(?!\d)', lambda m: '*' * (len(m.group(0)) - 4) + m.group(0)[-4:], text)


def _amount_candidate(row: dict, rows: list[dict]) -> bool:
    s = row['text'].lower()
    if re.search(r'\b(?:rp|idr|total|nominal|jumlah|amount|transfer)\b', s):
        return True
    if not AMOUNT_PATTERN.search(s):
        return False
    # Only add bare numeric lines when near context/other monetary lines.
    x0, y0, x1, y1 = row['bbox']
    mid_y = (y0 + y1) / 2
    return any('rp' in other['text'].lower() or any(k in other['text'].lower() for k in ('nominal', 'total', 'jumlah', 'amount', 'transfer'))
               for other in rows if other is not row and abs((other['bbox'][1] + other['bbox'][3]) / 2 - mid_y) < max(60, 3 * (y1-y0)))


def _roi_metrics(rgb: np.ndarray, box: list[int]) -> dict:
    """Texture vs adjacent ring, reported as diagnostics rather than a classifier."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = box
    margin = max(8, min(26, (y1-y0)//2))
    a, b, c, d = max(0, x0-margin), max(0, y0-margin), min(w, x1+margin), min(h, y1+margin)
    local = cv2.cvtColor(rgb[b:d, a:c], cv2.COLOR_RGB2GRAY)
    if min(local.shape) < 10:
        return {'status': 'region_too_small'}
    # Measure high-frequency energy around OCR text, not a claim that smooth==fake.
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    highpass = cv2.absdiff(gray, cv2.GaussianBlur(gray, (5, 5), 0)).astype(np.float32)
    center = highpass[y0:y1, x0:x1]
    expanded = highpass[b:d, a:c]
    mask = np.ones(expanded.shape, dtype=bool)
    mask[y0-b:y1-b, x0-a:x1-a] = False
    outside = expanded[mask]
    center_mean = float(center.mean()) if center.size else 0.0
    ring_mean = float(outside.mean()) if outside.size else 0.0
    # Neighboring pixels may naturally differ due to typography, logo or shading.
    return {'status': 'computed', 'high_frequency_inside': round(center_mean, 3),
            'high_frequency_ring': round(ring_mean, 3),
            'inside_to_ring_ratio': round((center_mean + 0.5)/(ring_mean + 0.5), 3),
            'interpretation': 'Diagnostik tekstur lokal; variasi font/background/kompresi juga memengaruhi hasil.'}


def inspect_amount_overlay(image: Image.Image, ocr_lines: list[dict] | None = None,
                           ocr_status: str | None = None) -> tuple[dict, Image.Image, list[Image.Image]]:
    """Returns JSON-safe diagnostic, annotated preview, and crops for Gemma 4."""
    arr = _image_array(image)
    h, w = arr.shape[:2]
    if ocr_lines is None:
        ocr_lines, status = extract_ocr_lines(Image.fromarray(arr))
    else:
        status = ocr_status or 'injected_for_test'
    rows = []
    for line in ocr_lines[:100]:
        b = line.get('bbox', None)
        if isinstance(b, (list, tuple)) and len(b) == 4:
            x0, y0, x1, y1 = [int(v) for v in b]
            if 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h:
                rows.append({'bbox': [x0,y0,x1,y1], 'text': str(line.get('text',''))[:120],
                             'confidence': float(line.get('confidence', 0.0))})
    amounts = [r for r in rows if _amount_candidate(r, rows)][:8]
    # Full image highpass heatmap is *visual aid* only. It is especially unreliable
    # for flat screenshots and deliberately never maps to a fraud probability.
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    residual = cv2.absdiff(gray, cv2.GaussianBlur(gray, (5, 5), 0))
    local_energy = cv2.GaussianBlur(residual, (0, 0), sigmaX=7)
    cap = max(1.0, float(np.percentile(local_energy, 98)))
    intensity = np.uint8(np.clip(local_energy.astype(np.float32) / cap * 255, 0, 255))
    heat_rgb = cv2.cvtColor(cv2.applyColorMap(intensity, cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
    preview = Image.fromarray(cv2.addWeighted(arr, 0.66, heat_rgb, 0.34, 0))
    draw = ImageDraw.Draw(preview)
    crops = []
    items = []
    for idx, row in enumerate(amounts):
        b = row['bbox']
        draw.rectangle(b, outline=(255, 55, 50), width=3)
        draw.text((b[0], max(0,b[1]-15)), f'ROI {idx + 1}', fill=(255,255,255), stroke_width=1, stroke_fill=(0,0,0))
        x0,y0,x1,y1 = b
        pad = max(25, int((y1-y0)*2))
        crops.append(Image.fromarray(arr).crop((max(0,x0-pad), max(0,y0-pad), min(w,x1+pad), min(h,y1+pad))))
        items.append({'bbox': b, 'text_redacted': _redact(row['text']),
                      'ocr_confidence': round(row['confidence'], 3), 'texture_diagnostic': _roi_metrics(arr,b)})
    result = {'status': status, 'approach': 'rapidocr_amount_roi_plus_opencv_diagnostic',
              'ocr_lines_count': len(rows), 'amount_candidates': items,
              'pixels_reviewed': [w,h],
              'interpretation': 'Heatmap bukan peta kemungkinan palsu. Ini hanya memperjelas tekstur/tepi piksel. '
                                'Gambar yang ditimpa nominal dan disimpan ulang bisa tidak meninggalkan jejak yang dapat dipastikan.',
              'limitations': ['Teks nominal yang belum dikenali OCR mungkin luput.',
                              'Tidak ada estimasi probabilitas fraud atau klasifikasi AI-generated.',
                              'ROI hanya menunjukkan area untuk pemeriksaan manual.']}
    return result, preview, crops


def compare_with_reference(target: Image.Image, genuine_reference: Image.Image) -> tuple[dict, Image.Image | None]:
    """Pixel-level comparison ONLY for same-resolution, *same-transaction* original.

    Not for comparing different transfers, unrelated bank templates or resized images.
    """
    a = np.asarray(target.convert('RGB'))
    b = np.asarray(genuine_reference.convert('RGB'))
    if a.shape != b.shape:
        return {'status': 'incompatible_dimensions',
                'detail': 'Referensi harus file asli dengan resolusi identik sebelum nominal diedit.'}, None
    h, w = a.shape[:2]
    if h*w > 24_000_000:
        return {'status':'too_many_pixels'}, None
    smooth_a = cv2.GaussianBlur(a, (3,3), 0).astype(np.float32)
    smooth_b = cv2.GaussianBlur(b, (3,3), 0).astype(np.float32)
    delta = np.max(np.abs(smooth_a-smooth_b), axis=2)
    # Threshold > expected small JPEG recompression differences (still not universal).
    mask = np.uint8(delta > 24) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3,3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15,5), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    regions = []
    for i in range(1, n):
        x,y,rw,rh,area = map(int, stats[i])
        if area >= max(20, int(h*w*0.00005)):
            regions.append({'bbox':[x,y,x+rw,y+rh], 'changed_pixel_count':area})
    regions.sort(key=lambda x: x['changed_pixel_count'], reverse=True)
    base = Image.fromarray(a).copy()
    drawn = ImageDraw.Draw(base)
    for r in regions[:20]:
        drawn.rectangle(r['bbox'], outline=(255,30,30), width=max(2,w//350))
    ratio = round(float((mask>0).mean()),6)
    return {'status':'completed', 'changed_pixel_fraction':ratio, 'changed_regions':regions[:20],
            'comparison_type': 'exact_same_resolution_original',
            'interpretation': 'Perbedaan piksel terhadap referensi terdeteksi, BUKAN otomatis bukti fraud. '
                              'Resave, kompresi, warna atau perubahan lain juga dapat menyebabkan perbedaan; '
                              'referensi wajib berasal dari file bukti transaksi yang sama.'}, base


def render_diagnostic_preview(image: Image.Image, amount_candidates: list[dict]) -> Image.Image:
    """Re-create heatmap + known ROI rectangles without invoking OCR a second time."""
    arr = _image_array(image)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    residual = cv2.absdiff(gray, cv2.GaussianBlur(gray, (5,5), 0))
    energy = cv2.GaussianBlur(residual, (0,0), sigmaX=7)
    denom = max(1.0, float(np.percentile(energy,98)))
    color = cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(energy/denom*255,0,255)),cv2.COLORMAP_TURBO),cv2.COLOR_BGR2RGB)
    preview = Image.fromarray(cv2.addWeighted(arr,0.66,color,0.34,0))
    draw = ImageDraw.Draw(preview)
    for i,r in enumerate(amount_candidates[:8]):
        b = r['bbox']
        draw.rectangle(b,outline=(255,55,50),width=3)
        draw.text((b[0],max(0,b[1]-15)),f'ROI {i+1}',fill=(255,255,255),stroke_width=1,stroke_fill=(0,0,0))
    return preview


def amount_crops(image: Image.Image, amount_candidates: list[dict]) -> list[Image.Image]:
    rgb = Image.fromarray(_image_array(image))
    w,h = rgb.size
    out = []
    for r in amount_candidates[:3]:
        x0,y0,x1,y1 = r['bbox']
        pad=max(25,2*(y1-y0))
        out.append(rgb.crop((max(0,x0-pad),max(0,y0-pad),min(w,x1+pad),min(h,y1+pad))))
    return out

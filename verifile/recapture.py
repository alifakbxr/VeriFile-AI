"""Conservative screen-*recapture* diagnostics (camera photographing a screen).

Never a stand-alone detector of fraud or a validated classifier. Geometry can
also describe paper receipts or ordinary UI panels, and JPEG/FFT peaks are
not calibrated evidence of screen moire. No network or extra model downloads.
"""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps


def _rect_candidate(bgr: np.ndarray) -> dict[str, Any] | None:
    """Find interior quadrilaterals for *review*, without calling them screens."""
    height, width = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edge = cv2.Canny(gray, 50, 150)
    edge = cv2.morphologyEx(edge, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:70]:
        perimeter = cv2.arcLength(contour, True)
        if perimeter < min(width, height):
            continue
        approx = cv2.approxPolyDP(contour, 0.022 * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        points = approx[:, 0, :].astype(np.float64)
        area_fraction = float(cv2.contourArea(approx) / (width * height))
        if area_fraction < 0.13 or area_fraction > 0.92:
            continue
        x, y, w, h = cv2.boundingRect(approx)
        # A complete border should exist within the photographed frame, not
        # coincide with crop edges; a cropped photo can evade this test.
        margin = min(x / width, y / height, (width - x - w) / width, (height - y - h) / height)
        if margin < 0.018 or w < 0.19 * width or h < 0.19 * height:
            continue
        length_ratio = max(w, h) / max(1, min(w, h))
        if length_ratio > 4.3:
            continue
        # Penalize borders that are likely ordinary horizontal UI panels.
        rect_area = max(1, w * h)
        fill_fraction = float(cv2.contourArea(approx) / rect_area)
        if fill_fraction < 0.45:
            continue
        # Right/left border tilt is useful for a human reviewer; avoid using
        # an uncalibrated threshold to assert recapture.
        box = cv2.boxPoints(cv2.minAreaRect(approx)).astype(np.float64)
        candidate = {
            'quadrilateral_xy': [[int(px), int(py)] for px, py in points],
            'area_fraction': round(area_fraction, 4),
            'bbox_xywh': [int(x), int(y), int(w), int(h)],
            'visible_margin_fraction': round(margin, 4),
            'rectangularity_fraction': round(fill_fraction, 4),
            'rotated_bounding_box_xy': [[int(px), int(py)] for px, py in box],
            'interpretation': 'Kontur persegi empat di dalam foto; mungkin layar HP, kertas, atau panel UI. Bukan identifikasi perangkat.',
        }
        candidates.append(candidate)
    return max(candidates, key=lambda c: (c['area_fraction'], c['visible_margin_fraction'])) if candidates else None


def _frequency_diagnostics(rgb: np.ndarray) -> dict[str, Any]:
    """Uncalibrated FFT observations. Repeated text/UI grids also create peaks."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_AREA).astype(np.float32)
    # Suppress slow illumination gradient, apply a window to avoid edge peaks.
    residual = gray - cv2.GaussianBlur(gray, (0, 0), sigmaX=6)
    tapered = residual * np.outer(np.hanning(256), np.hanning(256))
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(tapered)))
    yy, xx = np.ogrid[-128:128, -128:128]
    radius = np.sqrt(xx * xx + yy * yy)
    band = spectrum[(radius >= 22) & (radius <= 105)]
    peak_to_median = float(np.max(band) / max(1.0, np.median(band))) if band.size else 0.0
    # This diagnostic is NOT a moire detector or a classification score.
    return {
        'fft_high_frequency_peak_to_median': round(min(peak_to_median, 1e8), 2),
        'calibrated_for_moire': False,
        'interpretation': 'Puncak periodik bisa berasal dari moiré, kisi font, tabel, kompresi, atau desain. Perlu inspeksi dan dataset kalibrasi.',
    }


def inspect_screen_recapture(image: Image.Image, image_metadata: dict | None = None) -> tuple[dict, Image.Image | None]:
    """Report evidence of *how* an image was obtained, not whether content is real.

    EXIF camera metadata suggests a camera-origin file, but does not prove that
    the camera photographed a screen, and all metadata is editable.
    """
    original = ImageOps.exif_transpose(image).convert('RGB')
    copy = original.copy()
    copy.thumbnail((1000, 1000))
    rgb = np.asarray(copy)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    rect = _rect_candidate(bgr)
    exif = (image_metadata or {}).get('exif', {})
    camera = {key: str(exif[key])[:120] for key in ('Make', 'Model') if exif.get(key)}
    camera_origin = bool(camera)
    if rect is not None and camera_origin:
        status = 'review_possible_screen_recapture'
    elif rect is not None:
        status = 'rectangular_boundary_only'
    elif camera_origin:
        status = 'camera_metadata_only'
    else:
        status = 'no_specific_clue_observed'
    result = {
        'status': status,
        'camera_metadata_claims': camera,
        'camera_origin_metadata_present': camera_origin,
        'capture_time_interpretation': ('Waktu EXIF, bila tersedia, menunjuk waktu foto ulang menurut metadata; ' 
                                        'bukan waktu transaksi ataupun tanggal screenshot yang ditampilkan.'),
        'interior_quadrilateral_candidate': rect,
        'spectral_diagnostics_exploratory': _frequency_diagnostics(rgb),
        'not_tested': ['Refleksi layar', 'Pola refresh kamera-layar', 'Klasifikator moiré terkalibrasi',
                       'Liveness display', 'Deteksi HP dengan model object detection'],
        'limitations': [
            'Kamera memotret kertas ataupun layar; EXIF tidak membedakannya.',
            'Tepi panel UI atau dokumen fisik bisa menyerupai bingkai HP.',
            'Moire, pantulan, atau garis refresh dapat hilang saat dikompresi/dipotong; FFT bukan classifier.',
            'Foto layar yang di-crop ketat mungkin tidak memiliki kontur bingkai sama sekali.',
            'Foto layar tidak membuktikan pemalsuan maupun perubahan nominal; validasi ke sumber bank tetap diperlukan.',
        ],
    }
    preview = None
    if rect is not None:
        # Upscale points back to original resolution in case of a preview resize.
        sx, sy = original.width / copy.width, original.height / copy.height
        preview = original.copy()
        pen = ImageDraw.Draw(preview)
        corners = [(round(x * sx), round(y * sy)) for x, y in rect['quadrilateral_xy']]
        pen.line(corners + [corners[0]], fill=(255, 172, 0), width=max(2, original.width // 250))
    return result, preview

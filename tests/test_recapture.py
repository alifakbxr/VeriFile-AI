"""Minimal regression tests: geometry is a clue, not a trained classifier."""
import io

import numpy as np
from PIL import Image, ImageDraw

from verifile.forensics import analyze_bytes
from verifile.recapture import inspect_screen_recapture


def make_fake_phone_photo():
    photo = Image.new('RGB', (800, 920), '#c9bdb1')
    draw = ImageDraw.Draw(photo)
    # Intentional *illustration*, not an optical photo / screen recapture dataset.
    shell = [(165, 65), (625, 105), (595, 820), (132, 781)]
    glass = [(187, 109), (603, 143), (570, 778), (154, 744)]
    draw.polygon(shell, fill='#101820')
    draw.line(shell + [shell[0]], fill='#555d65', width=8)
    draw.polygon(glass, fill='#f8f8f8')
    draw.line(glass + [glass[0]], fill='#c1c8d2', width=6)
    draw.text((245, 320), 'SIMULASI', fill='#1a1a1a')
    draw.text((235, 365), 'Rp 990.000', fill='#1a1a1a')
    return photo


def test_screen_context_rectangle_is_only_candidate_without_camera():
    image = make_fake_phone_photo()
    diag, preview = inspect_screen_recapture(image)
    assert diag['status'] == 'rectangular_boundary_only'
    assert diag['interior_quadrilateral_candidate'] is not None
    assert preview is not None
    assert diag['spectral_diagnostics_exploratory']['calibrated_for_moire'] is False


def test_screen_context_review_requires_camera_metadata_and_rectangle():
    image = make_fake_phone_photo()
    data = io.BytesIO()
    exif = Image.Exif()
    exif[271] = 'SIMULATED_CAMERA'
    exif[272] = 'SIMULATED_MODEL'
    image.save(data, 'JPEG', quality=93, exif=exif)
    report, _, _ = analyze_bytes(data.getvalue(), 'synthetic_photo.jpg')
    diag = report['forensics']['recapture_diagnostics'][0]
    assert diag['status'] == 'review_possible_screen_recapture'
    assert diag['camera_metadata_claims']['Make'] == 'SIMULATED_CAMERA'
    assert any(f['code'] == 'screen_recapture_context' for f in report['forensics']['findings'])
    assert 'membuktikan' in report['forensics']['limitations'][-3].lower() or 'membuktikan' in ' '.join(diag['limitations']).lower()


def test_camera_exif_alone_not_labeled_screen():
    image = Image.new('RGB', (350, 500), '#999999')
    diag, _ = inspect_screen_recapture(image, {'exif': {'Make': 'Example', 'Model': 'Camera'}})
    assert diag['status'] == 'camera_metadata_only'
    assert diag['interior_quadrilateral_candidate'] is None


def test_blank_image_not_classified_as_screen_or_moire():
    image = Image.fromarray(np.full((240, 360, 3), 150, np.uint8))
    diag, _ = inspect_screen_recapture(image)
    assert diag['status'] == 'no_specific_clue_observed'
    assert diag['spectral_diagnostics_exploratory']['calibrated_for_moire'] is False

"""Conservative, local-only file triage. Nothing here proves fraud."""
from __future__ import annotations

import hashlib
import io
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import defusedxml.ElementTree as ET

import fitz
import numpy as np
from PIL import ExifTags, Image, ImageChops, ImageEnhance, ImageOps, UnidentifiedImageError

from .overlay import inspect_amount_overlay, compare_with_reference, _redact
from .recapture import inspect_screen_recapture
from .timeline import add_stamp, extract_xmp, extract_png_time, select_timeline, observed_filesystem_times

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_PAGES = 3
MAX_IMAGES = 3
MAX_PIXELS = 24_000_000
MAX_PDF_DIMENSION_POINTS = 5000
MAX_XML_MEMBER_BYTES = 10 * 1024 * 1024
SUPPORTED = {'jpeg', 'png', 'webp', 'pdf', 'docx'}

Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class UnsafeFile(ValueError):
    """Unrecognized, oversized or potentially unsafe input."""


def _finding(code: str, title: str, detail: str, severity: str = 'info', source: str = 'metadata') -> dict:
    return {'code': code, 'title': title, 'detail': detail, 'severity': severity, 'source': source}


def detect_type(data: bytes) -> str:
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data.startswith(b'%PDF-'):
        return 'pdf'
    if data.startswith(b'PK\x03\x04'):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                info = z.infolist()
                if len(info) > 500 or sum(x.file_size for x in info) > MAX_DOCX_EXPANDED_BYTES:
                    raise UnsafeFile('DOCX melebihi batas pengembangan arsip.')
                names = set(z.namelist())
                if {'[Content_Types].xml', 'word/document.xml'}.issubset(names):
                    return 'docx'
        except (zipfile.BadZipFile, OSError) as exc:
            raise UnsafeFile('Arsip ZIP tidak valid.') from exc
    raise UnsafeFile('Tipe file belum didukung. MVP: JPG, PNG, WebP, PDF, DOCX.')


def _text(v: Any, max_len: int = 250) -> str:
    return str(v).replace('\x00', '')[:max_len]


def _image_metadata(image: Image.Image, data: bytes, kind: str) -> tuple[dict, list[dict]]:
    metadata = {'width': image.width, 'height': image.height, 'format': image.format}
    stamps: list[dict] = []
    exif_tags: dict = {}
    try:
        exif = image.getexif()
        wanted = {'Artist', 'Software', 'Make', 'Model', 'DateTime', 'Copyright', 'HostComputer',
                  'DateTimeOriginal', 'DateTimeDigitized', 'OffsetTime', 'OffsetTimeOriginal', 'OffsetTimeDigitized'}
        for group in (exif, exif.get_ifd(ExifTags.IFD.Exif)):
            for tag, value in group.items():
                name = ExifTags.TAGS.get(tag, str(tag))
                if name in wanted:
                    exif_tags[name] = _text(value)
        for name, event, offset_name in (
            ('DateTimeOriginal','captured','OffsetTimeOriginal'),
            ('DateTimeDigitized','created','OffsetTimeDigitized'),
            ('DateTime','modified','OffsetTime'),
        ):
            if name in exif_tags:
                add_stamp(stamps, event, 'exif.' + name, exif_tags[name], offset=exif_tags.get(offset_name))
    except (ValueError, TypeError, KeyError, OSError):
        pass
    metadata['exif'] = exif_tags
    # PNG textual headers are unverified strings. Retain only common creator/date tags.
    desired = {'author', 'software', 'creation time', 'description', 'comment', 'title',
               'creator', 'date:create', 'date:modify', 'creation_time'}
    embedded = {str(k): _text(v) for k,v in image.info.items()
                if str(k).lower() in desired and isinstance(v, (str, int))}
    metadata['embedded_text'] = embedded
    for key, value in embedded.items():
        key_lower = key.lower()
        if key_lower in {'creation time', 'creation_time', 'date:create'}:
            add_stamp(stamps, 'created', 'png.' + key, value)
        elif key_lower == 'date:modify':
            add_stamp(stamps, 'modified', 'png.' + key, value)
    if kind == 'png':
        png_time = extract_png_time(data)
        if png_time:
            metadata['png_tIME_utc'] = png_time
            add_stamp(stamps, 'modified', 'png.tIME', png_time)
    # Pillow exposes XMP as bytes in many JPEG / WebP / PNG files. Bounded extraction.
    xmp_data = image.info.get('xmp') or image.info.get('XML:com.adobe.xmp')
    xmp_stamps, xmp_info = extract_xmp(xmp_data, 'xmp')
    stamps.extend(xmp_stamps)
    if xmp_info:
        metadata['xmp_selected'] = xmp_info
    return metadata, stamps


def _ela_preview(image: Image.Image) -> tuple[Image.Image, dict]:
    """JPEG recompression visualization; deliberately not treated as a fraud classifier."""
    rgb = ImageOps.exif_transpose(image).convert('RGB')
    rgb.thumbnail((1200, 1200))
    buffer = io.BytesIO()
    rgb.save(buffer, format='JPEG', quality=90)
    buffer.seek(0)
    with Image.open(buffer) as compressed:
        diff = ImageChops.difference(rgb, compressed.convert('RGB'))
        extrema = diff.getextrema()
        max_diff = max(x[1] for x in extrema)
        preview = ImageEnhance.Brightness(diff).enhance(255.0 / max(1, max_diff))
        arr = np.asarray(diff, dtype=np.uint8)
        stats = {'ela_mean_absolute_diff': round(float(arr.mean()), 3),
                 'ela_p95_absolute_diff': round(float(np.percentile(arr, 95)), 3),
                 'ela_note': 'ELA hanya visualisasi perbedaan JPEG; tinggi/rendahnya bukan bukti edit, AI, atau pemalsuan.'}
        return preview, stats


def _load_image(data: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > MAX_PIXELS:
                raise UnsafeFile('Resolusi gambar terlalu besar untuk pemeriksaan demo.')
            picture.load()
            result = picture.copy()
            result.format = picture.format
            return result
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsafeFile('Berkas gambar rusak atau gagal dibaca.') from exc


def _analyze_image(data: bytes, kind: str) -> tuple[dict, list, list, Image.Image | None]:
    img = _load_image(data)
    meta, stamps = _image_metadata(img, data, kind)
    meta['_timeline_stamps'] = stamps
    findings = []
    software = ' '.join([meta.get('exif', {}).get('Software', ''),
                         next((str(v) for k,v in meta.get('embedded_text', {}).items()
                               if k.lower() == 'software'), ''),
                         meta.get('xmp_selected', {}).get('CreatorTool', '')]).strip()
    if software:
        findings.append(_finding('editing_software', 'Jejak software pengolah file',
                                 f'Metadata mencantumkan software: {software}. Ini tidak membuktikan manipulasi bukti transfer.',
                                 'review'))
    else:
        findings.append(_finding('no_software_tag', 'Informasi software tidak tersedia',
                                 'Tidak ada tag software yang dapat diandalkan. Ketiadaannya normal pada banyak screenshot.'))
    views = [ImageOps.exif_transpose(img).convert('RGB')]
    preview = None
    if kind == 'jpeg':
        preview, stats = _ela_preview(img)
        meta['jpeg_recompression_diagnostic'] = stats
        findings.append(_finding('ela', 'Diagnostik JPEG ELA',
                                 'Visualisasi ELA tersedia untuk inspeksi manusia, bukan penentu asli/palsu.', 'info', 'pixel'))
    elif kind == 'png':
        findings.append(_finding('png_no_ela', 'ELA JPEG tidak diterapkan',
                                 'PNG menggunakan kompresi berbeda; uji ELA JPEG tidak berlaku.', 'info', 'pixel'))
    return meta, findings, views, preview


def _pdf_paint_order_overlays(page: fitz.Page) -> list[dict]:
    """Detect text -> filled rectangle -> text near same area, preserving paint order.

    This only works in non-flattened PDFs and is intentionally a candidate signal:
    whiteouts are often legitimate redactions, template elements or design changes.
    """
    events = page.get_bboxlog()[:4000]
    hits = []
    page_area = max(1, page.rect.get_area())
    for i, (kind, rect, *_) in enumerate(events):
        if kind != 'fill-path':
            continue
        patch = fitz.Rect(rect)
        if patch.is_empty or not (40 < patch.get_area() < page_area * 0.10):
            continue
        earlier = [(j,fitz.Rect(rect2)) for j,(k,rect2,*_) in enumerate(events[:i])
                   if k in {'fill-text', 'stroke-text'}]
        later = [(j+i+1,fitz.Rect(rect2)) for j,(k,rect2,*_) in enumerate(events[i+1:])
                 if k in {'fill-text', 'stroke-text'}]
        underlying = [j for j,t in earlier if t.get_area()>1 and (patch&t).get_area()/t.get_area() > 0.45]
        replacement = [j for j,t in later if t.get_area()>1 and (patch&t).get_area()/t.get_area() > 0.30]
        if underlying and replacement:
            hits.append({'bbox_pt': [round(v,2) for v in patch],
                         'underlying_text_events': underlying[:5],
                         'replacement_text_events': replacement[:5],
                         'overlay_draw_event': i})
    return hits[:20]


def _pdf_analysis(data: bytes) -> tuple[dict, list, list, Image.Image | None]:
    findings, pages = [], []
    try:
        with fitz.open(stream=data, filetype='pdf') as document:
            if document.needs_pass:
                raise UnsafeFile('PDF terenkripsi; buka proteksi secara sah sebelum dianalisis.')
            pdf_stamps: list[dict] = []
            doc_meta = (document.metadata or {})
            add_stamp(pdf_stamps, 'created', 'pdf.info.creationDate', doc_meta.get('creationDate'))
            add_stamp(pdf_stamps, 'modified', 'pdf.info.modDate', doc_meta.get('modDate'))
            # XMP metadata may contain timestamps different from the PDF Info dictionary.
            try:
                xmp_stamps, xmp_selected = extract_xmp(document.get_xml_metadata(), 'pdf.xmp')
                pdf_stamps.extend(xmp_stamps)
            except (ValueError, RuntimeError, AttributeError):
                xmp_selected = {'xmp_status': 'unavailable'}
            meta = {'page_count': document.page_count,
                    'document_metadata': {k: _text(v) for k, v in doc_meta.items() if v},
                    'xmp_selected': xmp_selected,
                    '_timeline_stamps': pdf_stamps,
                    'pages_inspected': min(document.page_count, MAX_PAGES),
                    'pages': []}
            if document.is_repaired:
                findings.append(_finding('repaired_pdf', 'Struktur PDF diperbaiki saat dibaca',
                                         'Parser PDF melakukan pemulihan struktur; ini bukan bukti pemalsuan.', 'review', 'structure'))
            for i in range(min(document.page_count, MAX_PAGES)):
                page = document.load_page(i)
                rect = page.rect
                if rect.width <= 0 or rect.height <= 0 or rect.width > MAX_PDF_DIMENSION_POINTS or rect.height > MAX_PDF_DIMENSION_POINTS:
                    raise UnsafeFile(f'Dimensi halaman PDF ({int(rect.width)}x{int(rect.height)}) di luar batas aman.')
                scale = min(1.35, (MAX_PIXELS / max(1.0, rect.width * rect.height)) ** 0.5)
                rendered = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                with Image.open(io.BytesIO(rendered.tobytes('png'))) as opened:
                    frame = opened.convert('RGB')
                    frame.thumbnail((1500, 1500))
                    pages.append(frame.copy())
                page_text = _redact(page.get_text('text')[:6000])
                annots = list(page.annots() or [])
                meta['pages'].append({'index': i + 1, 'selectable_text': page_text,
                                      'annotation_count': len(annots), 'embedded_image_count': len(page.get_images())})
                if annots:
                    findings.append(_finding('pdf_annotations', 'Anotasi PDF ditemukan',
                                             f'Halaman {i+1} memuat {len(annots)} anotasi. Anotasi legal dan umum; periksa konteks.',
                                             'review', 'structure'))
                vector_overlays = _pdf_paint_order_overlays(page)
                meta['pages'][-1]['text_cover_and_replace_candidates'] = vector_overlays
                if vector_overlays:
                    findings.append(_finding('pdf_text_cover_replace', 'Pola teks tertutup lalu diganti di PDF',
                                             f'Halaman {i+1}: {len(vector_overlays)} area memiliki urutan gambar '
                                             'teks → bidang pengisi → teks; periksa apakah penggantian resmi atau mencurigakan.',
                                             'review', 'structure'))
            if document.page_count > MAX_PAGES:
                findings.append(_finding('pdf_partial', 'Sebagian halaman belum dianalisis',
                                         f'MVP hanya meninjau {MAX_PAGES} halaman pertama dari {document.page_count} halaman.',
                                         'info', 'coverage'))
            if meta['document_metadata'].get('creator') or meta['document_metadata'].get('producer'):
                findings.append(_finding('pdf_creator', 'PDF producer/creator terdeteksi',
                                         'Producer/Creator tersedia pada metadata; pembuat dokumen bukan bukti identitas pengirim.',
                                         'info'))
            return meta, findings, pages, None
    except (fitz.FileDataError, fitz.EmptyFileError, RuntimeError) as exc:
        raise UnsafeFile('PDF tidak valid atau gagal dirender dengan aman.') from exc


def _safe_xml_parse(xml_data: bytes) -> ET.Element:
    if len(xml_data) > MAX_XML_MEMBER_BYTES or b'<!DOCTYPE' in xml_data.upper() or b'<!ENTITY' in xml_data.upper():
        raise UnsafeFile('XML DOCX memuat deklarasi entitas/DTD atau melebihi batas ukuran.')
    try:
        return ET.fromstring(xml_data)
    except Exception as exc:
        raise UnsafeFile('Struktur XML tidak valid.') from exc


def _docx_analysis(data: bytes) -> tuple[dict, list, list, Image.Image | None]:
    meta = {'core_properties': {}, 'text_preview': '', 'embedded_image_count': 0}
    docx_stamps: list[dict] = []
    findings, images = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > 500 or sum(x.file_size for x in infos) > MAX_DOCX_EXPANDED_BYTES:
            raise UnsafeFile('Arsip DOCX terlalu besar setelah ekstraksi.')
        names = set(z.namelist())
        if 'docProps/core.xml' in names:
            try:
                root = _safe_xml_parse(z.read('docProps/core.xml'))
                for element in root.iter():
                    key = element.tag.split('}')[-1]
                    if key in {'creator', 'lastModifiedBy', 'created', 'modified', 'revision', 'title'} and element.text:
                        meta['core_properties'][key] = _text(element.text)
                        if key in {'created', 'modified'}:
                            add_stamp(docx_stamps, key, 'docx.core.' + key, element.text)
            except (UnsafeFile, ET.ParseError):
                findings.append(_finding('corexml_invalid', 'Metadata DOCX gagal dibaca',
                                         'core.xml tidak dapat diparsing atau tidak aman.', 'review', 'structure'))
        try:
            root = _safe_xml_parse(z.read('word/document.xml'))
            pieces = [(el.text or '') for el in root.iter() if el.tag.endswith('}t')]
            meta['text_preview'] = _redact(' '.join(pieces)[:8000])
        except UnsafeFile:
            raise
        except ET.ParseError as exc:
            raise UnsafeFile('Isi XML DOCX tidak valid.') from exc
        # ZIP member times are stored as timezone-less DOS timestamps. They are
        # package-container clues only, not reliable file creation dates.
        meta['zip_entry_times_unverified'] = {name: '%04d-%02d-%02dT%02d:%02d:%02d' % z.getinfo(name).date_time
              for name in ('docProps/core.xml', 'word/document.xml') if name in names}
        names_media = [n for n in z.namelist() if n.startswith('word/media/') and n.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))]
        meta['embedded_image_count'] = len(names_media)
        for filename in names_media[:MAX_IMAGES]:
            try:
                file_data = z.read(filename)
                if len(file_data) > MAX_FILE_BYTES:
                    continue
                img = _load_image(file_data).convert('RGB')
                img.thumbnail((1400, 1400))
                images.append(img)
            except UnsafeFile:
                findings.append(_finding('docx_media_invalid', 'Gambar tertanam tidak terbaca',
                                         f'Gagal membaca {Path(filename).name}.', 'info', 'structure'))
        if meta['core_properties'].get('lastModifiedBy'):
            findings.append(_finding('docx_last_author', 'Last modified by tersedia',
                                     'Nama editor terakhir berasal dari metadata yang dapat diubah; bukan identitas terverifikasi.', 'info'))
        if meta['embedded_image_count'] > MAX_IMAGES:
            findings.append(_finding('docx_partial_media', 'Gambar tertanam dianalisis sebagian',
                                     f'Gambar diambil maksimal {MAX_IMAGES} dari {meta["embedded_image_count"]}.', 'info', 'coverage'))
    meta['_timeline_stamps'] = docx_stamps
    return meta, findings, images, None


def analyze_bytes(data: bytes, filename: str = 'upload', *, reference_bytes: bytes | None = None) -> tuple[dict, list[Image.Image], Image.Image | None]:
    if not data or len(data) > MAX_FILE_BYTES:
        raise UnsafeFile(f'Ukuran file harus 1 byte sampai {MAX_FILE_BYTES // 1024 // 1024} MB.')
    kind = detect_type(data)
    safe_name = Path(filename).name[:180]
    suffix = Path(safe_name).suffix.lower()
    expected = {'jpeg': {'.jpg', '.jpeg'}, 'png': {'.png'}, 'webp': {'.webp'}, 'pdf': {'.pdf'}, 'docx': {'.docx'}}
    findings = []
    if suffix not in expected[kind]:
        findings.append(_finding('extension_mismatch', 'Ekstensi berbeda dari isi file',
                                 f'Ekstensi {suffix or "(tidak ada)"}, signature: {kind}. Perlu verifikasi sumber file.',
                                 'review', 'structure'))
    if kind in {'jpeg', 'png', 'webp'}:
        meta, extra, views, ela = _analyze_image(data, kind)
    elif kind == 'pdf':
        meta, extra, views, ela = _pdf_analysis(data)
    else:
        meta, extra, views, ela = _docx_analysis(data)
    findings.extend(extra)
    stamps = meta.pop('_timeline_stamps', [])
    timeline, timeline_findings = select_timeline(stamps)
    timeline['timestamps'] = stamps
    findings.extend(timeline_findings)
    overlay_diagnostics = []
    recapture_diagnostics = []
    for page_index, view in enumerate(views[:MAX_IMAGES]):
        diagnostic, _, _ = inspect_amount_overlay(view)
        overlay_diagnostics.append({'visual_index': page_index, **diagnostic})
        # Camera tags apply to the uploaded image itself, not to PDF page renders.
        capture_meta = meta if kind in {'jpeg', 'png', 'webp'} and page_index == 0 else {}
        recapture, _ = inspect_screen_recapture(view, capture_meta)
        recapture_diagnostics.append({'visual_index': page_index, **recapture})
        if recapture['status'] == 'review_possible_screen_recapture':
            findings.append(_finding('screen_recapture_context', 'Kemungkinan foto ulang layar/perangkat',
                                     f'Visual {page_index + 1}: metadata kamera dan kontur interior ditemukan; ' 
                                     'bisa juga foto dokumen fisik. Tidak membuktikan pemalsuan.',
                                     'review', 'screen_recapture'))
        elif recapture['status'] == 'camera_metadata_only':
            findings.append(_finding('camera_origin_metadata', 'Metadata perangkat kamera tersedia',
                                     'File mengklaim dibuat kamera. Tidak membuktikan objeknya adalah layar HP.',
                                     'info', 'screen_recapture'))
        if diagnostic['amount_candidates']:
            findings.append(_finding('amount_roi_review', 'Area nominal ditemukan untuk diperiksa',
                                     f'Visual {page_index+1}: {len(diagnostic["amount_candidates"])} area potensial nominal; '
                                     'penandaan ROI bukan bukti nominal telah ditimpa.',
                                     'info', 'ocr'))
    ref_comparison = {'status': 'not_provided'}
    if reference_bytes is not None:
        if len(reference_bytes) > MAX_FILE_BYTES:
            raise UnsafeFile('Referensi asli melebihi batas 20 MB.')
        try:
            ref_kind = detect_type(reference_bytes)
            if kind not in {'jpeg', 'png', 'webp'} or ref_kind not in {'jpeg', 'png', 'webp'}:
                ref_comparison = {'status': 'unsupported', 'detail': 'Perbandingan hanya untuk dua file gambar.'}
            else:
                ref_comparison, _ = compare_with_reference(views[0], _load_image(reference_bytes))
                if ref_comparison['status'] == 'completed' and ref_comparison['changed_regions']:
                    findings.append(_finding('reference_pixel_differences', 'Perbedaan terhadap referensi transaksi yang sama',
                                             f'{len(ref_comparison["changed_regions"])} area berbeda dari referensi; '
                                             'pastikan sumber referensi autentik dan file benar-benar transaksi yang sama.',
                                             'review', 'comparison'))
        except UnsafeFile:
            ref_comparison = {'status': 'invalid_reference', 'detail': 'Referensi bukan gambar yang didukung.'}
    has_review = any(f['severity'] == 'review' for f in findings)
    outcome = 'Perlu pemeriksaan lanjutan' if has_review else 'Tidak ada indikator kuat dari pemeriksaan terbatas'
    result = {
        'schema_version': '0.4', 'file': {'name': safe_name, 'type_detected': kind,
                                          'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
        'analyzed_at_utc': datetime.now(timezone.utc).isoformat(),
        'forensics': {'metadata': meta, 'timeline': timeline, 'overlay_diagnostics': overlay_diagnostics, 'recapture_diagnostics': recapture_diagnostics,
                      'reference_comparison': ref_comparison, 'findings': findings, 'summary': outcome,
                      'limitations': ['Hasil tidak dapat memastikan transaksi telah terjadi.',
                                      'Metadata dan tanggal internal dapat diubah/dihapus, tidak membuktikan kapan transaksi terjadi.',
                                      'Waktu filesystem file yang diunggah dapat berasal dari Colab/Gradio, bukan perangkat asal.',
                                      'ELA dan pola piksel tidak bisa membuktikan gambar hasil AI.',
                                      'Ketiadaan tanda mencurigakan tidak membuktikan dokumen asli.',
                                      'Foto layar bisa menyamarkan jejak edit sebelumnya, tetapi foto layar sendiri tidak membuktikan penipuan.',
                                      'Tampilan setelah diedit dan diratakan bisa identik secara statistik dengan file normal.']},
        'gemma4': {'status': 'not_run', 'model': None, 'analysis': None},
        'verdict': 'TIDAK DAPAT DIVERIFIKASI tanpa data transaksi independen',
    }
    return result, views, ela


def analyze_file(path: str | Path, *, reference_path: str | Path | None = None,
                 use_exiftool: bool = False):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES:
        raise UnsafeFile('Berkas terlalu besar (maksimal 20 MB).')
    original = None
    if reference_path:
        reference_path = Path(reference_path)
        if reference_path.stat().st_size > MAX_FILE_BYTES:
            raise UnsafeFile('Referensi asli terlalu besar (maksimal 20 MB).')
        original = reference_path.read_bytes()
    result, images, ela = analyze_bytes(path.read_bytes(), path.name, reference_bytes=original)
    result['file']['observed_filesystem'] = observed_filesystem_times(path)
    if use_exiftool:
        from .exiftool_scan import enrich_report
        enrich_report(result, path)
    return result, images, ela

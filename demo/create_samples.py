"""Purely fictional local fixtures; no bank trademarks, genuine transactions or PII."""
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent


def font(size, bold=False):
    family = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    try:
        return ImageFont.truetype(family,size)
    except OSError:
        return ImageFont.load_default()


def make_image(name: str, edited: bool):
    im=Image.new('RGB',(900,630),'#e7edf5')
    d=ImageDraw.Draw(im)
    d.rounded_rectangle((60,35,840,595),radius=25,fill='white')
    d.rectangle((60,35,840,145),fill='#24436f')
    d.text((92,70),'DEMO PAYMENT / CONTOH',font=font(27,True),fill='white')
    d.text((90,176),'Bukti Transfer — SIMULASI',font=font(23,True),fill='#172b40')
    for y,label in [(255,'Status : Simulasi sukses'),(324,'Penerima : Akun Contoh'),
                    (462,'Referensi : TEST-00001')]:
        d.text((98,y),label,font=font(23),fill='#172b40')
    # Create an amount in the ORIGINAL first, then cover that exact region in the edited sample.
    d.text((98,390),'Nominal : Rp 120.000',font=font(29,True),fill='#172b40')
    if edited:
        # White patch simulates manual erase-and-overwrite in a common image editor.
        d.rectangle((91,382,640,434),fill='#ffffff')
        d.text((98,390),'Nominal : Rp 920.000',font=font(29,True),fill='#172b40')
    d.text((270,548),'DATA SINTETIS • BUKAN BUKTI BANK',font=font(16,True),fill='#9b3b47')
    im.save(OUT/name,quality=95)


def make_screen_photo_mock(name: str):
    """Synthetic *illustration*, not a camera photo or benchmark moire sample."""
    im = Image.new('RGB', (800, 920), '#c9bdb1')
    d = ImageDraw.Draw(im)
    frame = [(165, 65), (625, 105), (595, 820), (132, 781)]
    screen = [(187, 109), (603, 143), (570, 778), (154, 744)]
    d.polygon(frame, fill='#101820')
    d.line(frame + [frame[0]], fill='#555d65', width=8)
    d.polygon(screen, fill='#f8f8f8')
    d.line(screen + [screen[0]], fill='#c1c8d2', width=6)
    d.text((245, 320), 'SIMULASI LAYAR', font=font(17, True), fill='#1a1a1a')
    d.text((235, 365), 'Rp 990.000', font=font(21, True), fill='#1a1a1a')
    d.text((20, 870), 'MOCKUP: BUKAN FOTO FISIK / BUKAN BUKTI BANK', font=font(13), fill='#242424')
    exif = Image.Exif()
    exif[271] = 'SYNTHETIC-CAMERA-EXAMPLE'
    exif[272] = 'NOT-A-REAL-PHONE'
    im.save(OUT/name, quality=94, exif=exif)


def make_pdf(name: str,edited:bool):
    pdf=fitz.open()
    page=pdf.new_page(width=500,height=320)
    page.insert_text((55,50),'SINTETIS / BUKAN BUKTI BANK',fontsize=15)
    page.insert_text((55,128),'Nominal : Rp 120.000',fontsize=18)
    if edited:
        page.draw_rect(fitz.Rect(52,105,310,134),color=None,fill=(1,1,1))
        page.insert_text((55,128),'Nominal : Rp 920.000',fontsize=18)
    page.insert_text((55,175),'Referensi : TEST-00001',fontsize=12)
    pdf.save(OUT/name)
    pdf.close()


if __name__=='__main__':
    make_image('clean_sample.jpg',False)
    make_image('edited_sample.jpg',True)
    make_pdf('clean_sample.pdf',False)
    make_pdf('edited_overlay_sample.pdf',True)
    make_screen_photo_mock('screen_photo_illustration.jpg')
    print('Created five fully synthetic fixtures in demo/.')

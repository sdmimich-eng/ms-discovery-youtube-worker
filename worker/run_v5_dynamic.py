import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

import render_and_upload_v2 as worker
import run_v4_dynamic as base

W, H = base.W, base.H
TW, TH = base.TW, base.TH

_ORIGINAL_UPLOAD = worker.upload_youtube

CATEGORY_MAP = {
    'win-tipps.de': 'WINDOWS & PC',
    'drucker-tipps.de': 'DRUCKER & SCANNER',
    'router-tipps.de': 'ROUTER & WLAN',
    'fahrzeug-hilfe.de': 'AUTO & FAHRZEUG',
    'app-fix.de': 'APPS & SMARTPHONE',
    'streamhilfe.de': 'STREAMING',
    'zeichencheck.de': 'ZEICHEN & SYMBOLE',
    'gartenpapst.de': 'GARTEN',
    'bautipps24.de': 'BAUEN & RENOVIEREN',
    'wohnungstipps24.de': 'WOHNEN',
    'wassollichheutekochen.de': 'KOCHEN & REZEPTE',
    'meingeld24.de': 'GELD & FINANZEN',
    'zahnersatz-hilfe.de': 'ZÄHNE & KOSTEN',
    'ebike-hilfe.de': 'E-BIKE',
    'kastenwagentipps.de': 'CAMPER & KASTENWAGEN',
    'putzpilot.de': 'PUTZEN & HAUSHALT',
    'nashilfe.de': 'NAS & SPEICHER',
    'server-preis.de': 'SERVER & HOSTING',
    'spielanleitungen.de': 'SPIELE & REGELN',
    'stadtlandfluss24.de': 'STADT LAND FLUSS',
    'wohin24.de': 'FREIZEIT & EVENTS',
    'tolleziele.de': 'AUSFLUGSZIELE',
    'preisstation.de': 'PREISE & KOSTEN',
    'pv-tipps.de': 'PHOTOVOLTAIK',
    'pv-check.de': 'PHOTOVOLTAIK',
    'bierwertung.de': 'BIER',
    'bierfestival.de': 'BIER & FESTIVALS',
}


def clean(value):
    return worker.clean_text(value)


def font(size, bold=False):
    path = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(path, size) if Path(path).exists() else ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words = clean(text).split()
    lines = []
    current = ''
    for word in words:
        candidate = (current + ' ' + word).strip()
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fit_text(draw, text, max_width, max_lines, start_size, min_size=32, step=2, bold=True):
    text = clean(text)
    for size in range(start_size, min_size - 1, -step):
        fnt = font(size, bold)
        lines = wrap(draw, text, fnt, max_width)
        if len(lines) <= max_lines:
            return fnt, lines
    fnt = font(min_size, bold)
    return fnt, wrap(draw, text, fnt, max_width)


def category_label(domain):
    d = clean(domain).lower().replace('www.', '')
    if d in CATEGORY_MAP:
        return CATEGORY_MAP[d]
    stem = d.split('.')[0].replace('-', ' ').strip().upper()
    if not stem:
        return 'RATGEBER'
    if len(stem) > 24:
        stem = stem[:24].rstrip()
    return stem


def clickable_url(value, fallback=''):
    url = clean(value or fallback)
    if not url:
        return ''
    if url.startswith('//'):
        return 'https:' + url
    if re.match(r'^https?://', url, re.I):
        return url
    if url.startswith('/'):
        base_url = clean(fallback)
        if re.match(r'^https?://', base_url, re.I):
            try:
                parsed = urlparse(base_url)
                return f'{parsed.scheme}://{parsed.netloc}{url}'
            except Exception:
                pass
    return 'https://' + url.lstrip('/')


def build_narration(title, text):
    ss = base.sentences(text)
    if not ss:
        ss = [clean(text)] if clean(text) else []

    selected = []
    total_chars = 0
    for sentence in ss:
        sentence = clean(sentence)
        if not sentence:
            continue
        if total_chars + len(sentence) > 3500:
            break
        selected.append(sentence)
        total_chars += len(sentence)

    if not selected:
        selected = ['Die wichtigsten Hinweise findest du im verlinkten Ratgeber.']

    blocks = []
    for i in range(0, len(selected), 3):
        part = selected[i:i + 3]
        if i == 3:
            part.insert(0, 'Schauen wir jetzt auf den nächsten wichtigen Punkt.')
        elif i == 6:
            part.insert(0, 'Wichtig ist außerdem Folgendes.')
        blocks.append(' '.join(part))

    intro = (
        f'{clean(title)}. '
        'Wir gehen direkt ins Thema: zuerst das Wichtigste, dann die sinnvollsten nächsten Schritte. '
    )
    outro = (
        'Wenn du alle Schritte, Details und Aktualisierungen sehen möchtest: '
        'Der direkte Link zum vollständigen Ratgeber steht ganz oben in der Videobeschreibung.'
    )
    return clean(intro + ' '.join(blocks) + ' ' + outro)


def make_intro_overlay(title, domain, out):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((68, 92, 1015, 955), radius=44, fill=(4, 10, 22, 218))
    d.rounded_rectangle((68, 92, 88, 955), radius=10, fill=(42, 207, 246, 255))

    cat = category_label(domain)
    cat_font, cat_lines = fit_text(d, cat, 560, 1, 35, 28, 1, True)
    cat_w = d.textbbox((0, 0), cat_lines[0], font=cat_font)[2]
    pill_right = min(930, 145 + cat_w + 72)
    d.rounded_rectangle((130, 145, pill_right, 218), radius=22, fill=(42, 207, 246, 255))
    d.text((165, 161), cat_lines[0], font=cat_font, fill=(3, 16, 30, 255))
    d.text((790, 158), 'MS RATGEBER', font=font(26, True), fill=(205, 225, 240, 255), anchor='ra')

    title_font, lines = fit_text(d, title, 760, 6, 72, 42, 2, True)
    line_h = int(title_font.size * 1.16) if hasattr(title_font, 'size') else 74
    y = 285
    for line in lines:
        d.text((135, y), line, font=title_font, fill='white')
        y += line_h

    d.rounded_rectangle((132, 842, 865, 915), radius=22, fill=(255, 255, 255, 22))
    d.text((165, 860), 'Kurz erklärt · mit konkreten nächsten Schritten', font=font(28, False), fill=(226, 237, 247, 255))
    d.text((136, 930), domain, font=font(25, True), fill=(103, 221, 255, 255))
    im.save(out)


def make_content_overlay(title, heading, pts, domain, idx, total, out, compact=False):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = category_label(domain)

    if compact:
        d.rounded_rectangle((72, 690, 1848, 1022), radius=34, fill=(4, 10, 22, 211))
        d.rounded_rectangle((72, 690, 92, 1022), radius=10, fill=(42, 207, 246, 255))
        d.rounded_rectangle((130, 728, 455, 780), radius=16, fill=(42, 207, 246, 238))
        cfont, clines = fit_text(d, cat, 280, 1, 25, 20, 1, True)
        d.text((155, 739), clines[0], font=cfont, fill=(4, 15, 28, 255))
        d.text((1710, 741), f'{idx}/{total}', font=font(25, True), fill=(115, 224, 255, 255))

        hfont, hlines = fit_text(d, heading, 1500, 1, 48, 36, 2, True)
        d.text((135, 808), hlines[0], font=hfont, fill='white')
        one = pts[0] if pts else ''
        pfont, plines = fit_text(d, one, 1510, 2, 31, 25, 1, False)
        y = 878
        for line in plines[:2]:
            d.text((135, y), line, font=pfont, fill=(236, 243, 249, 255))
            y += int(getattr(pfont, 'size', 31) * 1.32)
    else:
        d.rounded_rectangle((70, 110, 1010, 970), radius=40, fill=(4, 10, 22, 211))
        d.rounded_rectangle((70, 110, 90, 970), radius=10, fill=(42, 207, 246, 255))
        d.rounded_rectangle((132, 155, 500, 216), radius=18, fill=(42, 207, 246, 238))
        cfont, clines = fit_text(d, cat, 318, 1, 28, 21, 1, True)
        d.text((160, 168), clines[0], font=cfont, fill=(4, 15, 28, 255))
        d.text((885, 170), f'{idx}/{total}', font=font(28, True), fill=(110, 224, 255, 255))

        hfont, hlines = fit_text(d, heading, 760, 2, 57, 42, 2, True)
        y = 270
        for line in hlines[:2]:
            d.text((140, y), line, font=hfont, fill='white')
            y += int(getattr(hfont, 'size', 56) * 1.17)

        y += 28
        for p in pts[:2]:
            d.rounded_rectangle((138, y + 8, 169, y + 39), radius=8, fill=(42, 207, 246, 255))
            d.text((148, y + 5), '›', font=font(27, True), fill=(4, 15, 28, 255))
            pfont, plines = fit_text(d, p, 690, 3, 32, 26, 1, False)
            for line in plines[:3]:
                d.text((195, y), line, font=pfont, fill=(239, 245, 250, 255))
                y += int(getattr(pfont, 'size', 31) * 1.32)
            y += 25

        bar_x1, bar_x2 = 140, 915
        d.rounded_rectangle((bar_x1, 900, bar_x2, 914), radius=7, fill=(255, 255, 255, 45))
        frac = max(0.04, min(1.0, idx / max(1, total)))
        d.rounded_rectangle((bar_x1, 900, bar_x1 + int((bar_x2 - bar_x1) * frac), 914), radius=7, fill=(42, 207, 246, 255))
        d.text((140, 928), domain, font=font(24, True), fill=(195, 215, 230, 255))

    im.save(out)


def make_cta_overlay(short_url, domain, out):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((180, 205, 1740, 875), radius=54, fill=(4, 10, 22, 225))
    d.rounded_rectangle((180, 205, 204, 875), radius=10, fill=(42, 207, 246, 255))
    d.rounded_rectangle((270, 278, 660, 346), radius=20, fill=(42, 207, 246, 245))
    d.text((305, 294), 'DIREKT ZUM RATGEBER', font=font(28, True), fill=(3, 15, 28, 255))
    d.text((270, 395), 'Alle Schritte & Details', font=font(72, True), fill='white')
    d.text((270, 500), 'Der Link steht ganz oben in der Beschreibung:', font=font(35, False), fill=(226, 238, 248, 255))

    link = clickable_url(short_url)
    lfont, llines = fit_text(d, link, 1280, 2, 45, 31, 1, True)
    y = 585
    for line in llines[:2]:
        d.text((270, y), line, font=lfont, fill=(96, 222, 255, 255))
        y += int(getattr(lfont, 'size', 42) * 1.28)
    d.text((270, 785), domain, font=font(29, True), fill=(195, 215, 230, 255))
    im.save(out)


def make_thumbnail(bg_path, title, domain, out):
    try:
        if bg_path and Path(bg_path).exists():
            bg = Image.open(bg_path).convert('RGB')
        else:
            bg = Image.new('RGB', (TW, TH), (11, 24, 44))
        ratio = max(TW / bg.width, TH / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        bg = bg.crop(((bg.width - TW) // 2, (bg.height - TH) // 2, (bg.width - TW) // 2 + TW, (bg.height - TH) // 2 + TH))
    except Exception:
        bg = Image.new('RGB', (TW, TH), (11, 24, 44))

    d = ImageDraw.Draw(bg, 'RGBA')
    for x in range(0, 835, 3):
        alpha = int(238 * (1 - x / 900))
        d.rectangle((x, 0, x + 3, TH), fill=(2, 8, 18, max(28, alpha)))

    cat = category_label(domain)
    cfont, clines = fit_text(d, cat, 520, 1, 36, 27, 1, True)
    cat_text = clines[0]
    cat_w = d.textbbox((0, 0), cat_text, font=cfont)[2]
    pill_right = min(700, 52 + cat_w + 82)
    d.rounded_rectangle((42, 42, pill_right, 120), radius=22, fill=(42, 207, 246, 250))
    d.text((78, 60), cat_text, font=cfont, fill=(3, 16, 30, 255))

    tfont, lines = fit_text(d, title, 700, 6, 68, 36, 2, True)
    line_h = int(getattr(tfont, 'size', 60) * 1.14)
    total_h = line_h * len(lines)
    y = max(148, min(205, 362 - total_h // 2))
    for line in lines:
        d.text((49, y + 3), line, font=tfont, fill=(0, 0, 0, 175))
        d.text((45, y), line, font=tfont, fill='white')
        y += line_h

    d.rounded_rectangle((42, 621, 540, 684), radius=18, fill=(3, 12, 25, 220))
    d.text((72, 637), domain, font=font(27, True), fill=(116, 225, 255, 255))
    d.rounded_rectangle((1040, 42, 1238, 102), radius=18, fill=(3, 12, 25, 205))
    d.text((1072, 58), 'MS RATGEBER', font=font(23, True), fill=(235, 243, 250, 255))
    bg.save(out, quality=95)


def motion_filter(mode, dur):
    if mode % 6 == 0:
        x = "iw/2-(iw/zoom/2)+sin(on/28)*34"
        y = "ih/2-(ih/zoom/2)+cos(on/44)*18"
        z = "min(zoom+0.00072,1.16)"
    elif mode % 6 == 1:
        x = "iw/2-(iw/zoom/2)-sin(on/32)*40"
        y = "ih/2-(ih/zoom/2)+sin(on/47)*20"
        z = "min(zoom+0.00064,1.145)"
    elif mode % 6 == 2:
        x = "iw/2-(iw/zoom/2)+cos(on/34)*30"
        y = "ih/2-(ih/zoom/2)-sin(on/39)*24"
        z = "min(zoom+0.00078,1.17)"
    elif mode % 6 == 3:
        x = "iw/2-(iw/zoom/2)-cos(on/31)*36"
        y = "ih/2-(ih/zoom/2)-cos(on/49)*18"
        z = "min(zoom+0.00069,1.155)"
    elif mode % 6 == 4:
        x = "iw/2-(iw/zoom/2)+sin(on/41)*26"
        y = "ih/2-(ih/zoom/2)-cos(on/35)*25"
        z = "min(zoom+0.00082,1.18)"
    else:
        x = "iw/2-(iw/zoom/2)-sin(on/37)*31"
        y = "ih/2-(ih/zoom/2)+cos(on/33)*22"
        z = "min(zoom+0.00074,1.165)"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps=30"


def render_motion_clip(bg, overlay, out, dur, mode=0):
    vf = motion_filter(mode, dur)
    fade_out_start = max(0.3, float(dur) - 0.28)
    fc = (
        f"[0:v]scale=2400:1350:force_original_aspect_ratio=increase,crop=2400:1350,"
        f"eq=contrast=1.055:saturation=1.09,{vf}[m];"
        f"[1:v]format=rgba,fade=t=in:st=0:d=0.34:alpha=1,"
        f"fade=t=out:st={fade_out_start:.3f}:d=0.26:alpha=1[ov];"
        f"[m][ov]overlay=x='if(lt(t,0.48),46*(1-t/0.48),0)':y=0:eval=frame:format=auto,"
        f"format=yuv420p[v]"
    )
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', str(bg), '-loop', '1', '-i', str(overlay),
        '-t', f'{dur:.3f}', '-filter_complex', fc, '-map', '[v]', '-an', '-r', '30',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p', str(out)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def upload_youtube_v5(video, job):
    enriched = dict(job)
    article_url = clickable_url(job.get('article_url', ''))
    direct_url = clickable_url(
        job.get('short_url') or job.get('source_url') or job.get('article_url', ''),
        article_url,
    )
    domain = worker.domain_label(article_url or direct_url)
    home_url = f'https://{domain}/' if domain and '.' in domain else ''

    original = (job.get('description') or '').strip()
    parts = []
    if direct_url:
        parts.extend(['👉 Vollständiger Ratgeber:', direct_url, ''])
    if original:
        parts.extend([original, ''])
    if home_url and home_url not in original and home_url != direct_url:
        parts.extend(['Weitere hilfreiche Ratgeber:', home_url, ''])
    parts.append('MS Ratgeber – verständlich erklärt und direkt zur ausführlichen Anleitung.')
    enriched['description'] = '\n'.join(parts).strip()[:5000]
    return _ORIGINAL_UPLOAD(video, enriched)


def install_v5():
    base.build_narration = build_narration
    base.make_intro_overlay = make_intro_overlay
    base.make_content_overlay = make_content_overlay
    base.make_cta_overlay = make_cta_overlay
    base.make_thumbnail = make_thumbnail
    base.motion_filter = motion_filter
    base.render_motion_clip = render_motion_clip
    worker.upload_youtube = upload_youtube_v5


def main():
    install_v5()
    return base.main()


if __name__ == '__main__':
    raise SystemExit(main())

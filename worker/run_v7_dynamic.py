import re
from pathlib import Path

from PIL import Image, ImageDraw

import render_and_upload_v2 as worker
import run_v4_dynamic as base
import run_v5_dynamic as v5
import run_v6_dynamic as v6

W, H = base.W, base.H
TW, TH = base.TW, base.TH


def display_clean(value):
    """Clean visible video text and remove generated truncation markers."""
    text = v6.clean_text(value)
    text = re.sub(r'\s*(?:\.{3,}|…)+\s*$', '', text).strip()
    return text


def complete_display_units(text, max_words=16):
    """Return short readable units without ever adding ellipses."""
    text = display_clean(text)
    if not text:
        return []

    units = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = display_clean(sentence)
        if not sentence:
            continue

        clauses = [display_clean(x) for x in re.split(r'(?<=[,;:])\s+', sentence) if display_clean(x)]
        if not clauses:
            clauses = [sentence]

        for clause in clauses:
            words = clause.split()
            if len(words) <= max_words:
                units.append(clause)
                continue

            # Long clauses are split into readable phrase-sized cards. No "..." is added.
            start = 0
            while start < len(words):
                end = min(len(words), start + max_words)
                part = ' '.join(words[start:end]).strip(' ,;:')
                if part:
                    units.append(part)
                start = end

    return units or ([text] if text else [])


def no_truncate_bullets(text, limit=2, chars=9999):
    units = complete_display_units(text, 15)
    return units[:max(1, limit)]


def strict_fit(draw, text, max_width, max_lines, start_size, min_size, bold=True):
    """Fit all text. Never return a line set that will be sliced afterward."""
    text = display_clean(text)
    for size in range(start_size, min_size - 1, -2):
        fnt = v5.font(size, bold)
        lines = v5.wrap(draw, text, fnt, max_width)
        if len(lines) <= max_lines:
            return fnt, lines

    # Visible texts passed to this layer are already short. If still too wide,
    # go slightly smaller rather than cutting words or appending ellipses.
    size = min_size
    while size >= 26:
        fnt = v5.font(size, bold)
        lines = v5.wrap(draw, text, fnt, max_width)
        if len(lines) <= max_lines:
            return fnt, lines
        size -= 1

    fnt = v5.font(26, bold)
    return fnt, v5.wrap(draw, text, fnt, max_width)


def make_intro_overlay(title, domain, out):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)

    d.rounded_rectangle((64, 86, 1080, 965), radius=44, fill=(4, 10, 22, 220))
    d.rounded_rectangle((64, 86, 86, 965), radius=10, fill=(42, 207, 246, 255))

    cfont, clines = strict_fit(d, cat, 590, 1, 35, 28, True)
    ctext = clines[0] if clines else cat
    cw = d.textbbox((0, 0), ctext, font=cfont)[2]
    d.rounded_rectangle((128, 142, min(880, 210 + cw), 218), radius=22, fill=(42, 207, 246, 250))
    d.text((164, 160), ctext, font=cfont, fill=(3, 16, 30, 255))
    d.text((995, 164), 'MS RATGEBER', font=v5.font(27, True), fill=(215, 231, 244, 255), anchor='ra')

    title = display_clean(title)
    tfont, lines = strict_fit(d, title, 825, 7, 72, 38, True)
    line_h = int(getattr(tfont, 'size', 58) * 1.15)
    total_h = line_h * len(lines)
    y = max(275, 560 - total_h // 2)
    for line in lines:
        d.text((138, y), line, font=tfont, fill='white')
        y += line_h

    d.rounded_rectangle((132, 842, 900, 915), radius=22, fill=(255, 255, 255, 24))
    d.text((165, 860), 'Kurz erklärt · klar · direkt zum Beitrag', font=v5.font(29, False), fill=(229, 239, 248, 255))
    d.text((138, 930), domain, font=v5.font(26, True), fill=(103, 221, 255, 255))
    im.save(out)


def make_content_overlay(title, heading, pts, domain, idx, total, out, compact=False):
    """Adaptive card layouts with guaranteed complete visible text."""
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)
    heading = display_clean(heading)

    clean_pts = []
    for p in pts or []:
        clean_pts.extend(complete_display_units(p, 15))
    clean_pts = clean_pts[:2]

    variant = idx % 4
    if compact:
        box = (72, 690, 1848, 1022)
        d.rounded_rectangle(box, radius=34, fill=(4, 10, 22, 214))
        d.rounded_rectangle((72, 690, 94, 1022), radius=10, fill=(42, 207, 246, 255))
        d.rounded_rectangle((130, 728, 510, 782), radius=16, fill=(42, 207, 246, 244))
        cfont, clines = strict_fit(d, cat, 330, 1, 26, 21, True)
        d.text((155, 740), clines[0], font=cfont, fill=(4, 15, 28, 255))
        d.text((1715, 742), f'{idx}/{total}', font=v5.font(26, True), fill=(115, 224, 255, 255))

        hfont, hlines = strict_fit(d, heading, 1510, 1, 49, 38, True)
        d.text((135, 808), hlines[0], font=hfont, fill='white')

        phrase = clean_pts[0] if clean_pts else ''
        pfont, plines = strict_fit(d, phrase, 1510, 2, 34, 29, False)
        y = 878
        for line in plines:
            d.text((135, y), line, font=pfont, fill=(238, 244, 249, 255))
            y += int(getattr(pfont, 'size', 31) * 1.30)
        im.save(out)
        return

    # Alternate left/right cards automatically so successive scenes do not feel templated.
    if variant in (0, 2):
        box = (70, 105, 1015, 970)
        tx = 140
        accent_x = 70
    else:
        box = (905, 105, 1850, 970)
        tx = 975
        accent_x = 1828

    d.rounded_rectangle(box, radius=40, fill=(4, 10, 22, 212))
    d.rounded_rectangle((accent_x, 105, accent_x + 22, 970), radius=10, fill=(42, 207, 246, 255))

    chip_x = tx - 8
    d.rounded_rectangle((chip_x, 154, chip_x + 385, 217), radius=18, fill=(42, 207, 246, 244))
    cfont, clines = strict_fit(d, cat, 325, 1, 28, 22, True)
    d.text((chip_x + 27, 168), clines[0], font=cfont, fill=(4, 15, 28, 255))

    count_x = box[2] - 86
    d.text((count_x, 171), f'{idx}/{total}', font=v5.font(28, True), fill=(110, 224, 255, 255), anchor='ra')

    hfont, hlines = strict_fit(d, heading, 740, 2, 57, 43, True)
    y = 275
    for line in hlines:
        d.text((tx, y), line, font=hfont, fill='white')
        y += int(getattr(hfont, 'size', 54) * 1.16)

    y += 30
    for p in clean_pts:
        d.rounded_rectangle((tx, y + 8, tx + 31, y + 39), radius=8, fill=(42, 207, 246, 255))
        d.text((tx + 10, y + 4), '›', font=v5.font(27, True), fill=(4, 15, 28, 255))
        pfont, plines = strict_fit(d, p, 675, 3, 34, 29, False)
        for line in plines:
            d.text((tx + 54, y), line, font=pfont, fill=(239, 245, 250, 255))
            y += int(getattr(pfont, 'size', 32) * 1.31)
        y += 26

    bar_x1, bar_x2 = tx, box[2] - 95
    d.rounded_rectangle((bar_x1, 900, bar_x2, 914), radius=7, fill=(255, 255, 255, 45))
    frac = max(0.04, min(1.0, idx / max(1, total)))
    d.rounded_rectangle((bar_x1, 900, bar_x1 + int((bar_x2 - bar_x1) * frac), 914), radius=7, fill=(42, 207, 246, 255))
    d.text((tx, 930), domain, font=v5.font(25, True), fill=(198, 217, 232, 255))
    im.save(out)


def flash_phrase(text, max_words=13):
    units = complete_display_units(text, max_words)
    return units[0] if units else display_clean(text)


def make_flash_overlay(text, domain, idx, total, out, variant=0):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)
    phrase = flash_phrase(text)

    layouts = [
        ((210, 220, 1710, 855), 315, 410, 'WICHTIG'),
        ((105, 255, 1500, 905), 205, 455, 'KURZ GESAGT'),
        ((420, 170, 1815, 855), 530, 390, 'NÄCHSTER SCHRITT'),
        ((255, 175, 1665, 875), 365, 405, 'DARAUF KOMMT ES AN'),
    ]
    box, text_x, text_y, label = layouts[variant % len(layouts)]

    d.rounded_rectangle(box, radius=48, fill=(4, 10, 22, 220))
    d.rounded_rectangle((box[0], box[1], box[0] + 22, box[3]), radius=10, fill=(42, 207, 246, 255))
    label_w = 480 if len(label) > 14 else 410
    d.rounded_rectangle((text_x, box[1] + 70, text_x + label_w, box[1] + 140), radius=21, fill=(42, 207, 246, 250))
    d.text((text_x + 34, box[1] + 87), label, font=v5.font(28, True), fill=(3, 16, 30, 255))

    fnt, lines = strict_fit(d, phrase, box[2] - text_x - 115, 5, 74, 42, True)
    line_h = int(getattr(fnt, 'size', 60) * 1.16)
    y = text_y
    for line in lines:
        d.text((text_x + 4, y + 4), line, font=fnt, fill=(0, 0, 0, 145))
        d.text((text_x, y), line, font=fnt, fill='white')
        y += line_h

    d.text((box[0] + 95, box[3] - 90), cat, font=v5.font(28, True), fill=(103, 221, 255, 255))
    d.text((box[2] - 95, box[3] - 90), f'{idx}/{total}', font=v5.font(28, True), fill=(205, 223, 237, 255), anchor='ra')
    im.save(out)


def make_thumbnail(bg_path, title, domain, out):
    try:
        bg = Image.open(bg_path).convert('RGB') if bg_path and Path(bg_path).exists() else Image.new('RGB', (TW, TH), (11, 24, 44))
        ratio = max(TW / bg.width, TH / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        bg = bg.crop(((bg.width - TW) // 2, (bg.height - TH) // 2, (bg.width - TW) // 2 + TW, (bg.height - TH) // 2 + TH))
    except Exception:
        bg = Image.new('RGB', (TW, TH), (11, 24, 44))

    d = ImageDraw.Draw(bg, 'RGBA')
    for x in range(0, 855, 3):
        alpha = int(240 * (1 - x / 920))
        d.rectangle((x, 0, x + 3, TH), fill=(2, 8, 18, max(30, alpha)))

    cat = v5.category_label(domain)
    cfont, clines = strict_fit(d, cat, 535, 1, 36, 28, True)
    ctext = clines[0]
    cw = d.textbbox((0, 0), ctext, font=cfont)[2]
    d.rounded_rectangle((42, 42, min(720, 125 + cw), 120), radius=22, fill=(42, 207, 246, 252))
    d.text((78, 60), ctext, font=cfont, fill=(3, 16, 30, 255))

    title = display_clean(title)
    tfont, lines = strict_fit(d, title, 715, 7, 68, 36, True)
    line_h = int(getattr(tfont, 'size', 58) * 1.13)
    total_h = line_h * len(lines)
    y = max(145, min(205, 365 - total_h // 2))
    for line in lines:
        d.text((49, y + 3), line, font=tfont, fill=(0, 0, 0, 175))
        d.text((45, y), line, font=tfont, fill='white')
        y += line_h

    d.rounded_rectangle((42, 621, 555, 684), radius=18, fill=(3, 12, 25, 222))
    d.text((72, 637), domain, font=v5.font(27, True), fill=(116, 225, 255, 255))
    d.rounded_rectangle((1040, 42, 1238, 102), radius=18, fill=(3, 12, 25, 208))
    d.text((1072, 58), 'MS RATGEBER', font=v5.font(23, True), fill=(235, 243, 250, 255))
    bg.save(out, quality=96)


def install_v7():
    # V6 keeps its working link/QR/entity/image-filter logic. V7 only upgrades visuals/readability.
    base.bullets = no_truncate_bullets
    v5.make_intro_overlay = make_intro_overlay
    v5.make_content_overlay = make_content_overlay
    v5.make_thumbnail = make_thumbnail
    v6.flash_phrase = flash_phrase
    v6.make_flash_overlay = make_flash_overlay


def main():
    install_v7()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

import re

from PIL import Image, ImageDraw

import render_and_upload_v2 as worker
import run_v2_filtered as filtered
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v7_dynamic as v7
import run_v9_dynamic as v9
import run_v11_dynamic as v11

W, H = 1920, 1080
_ORIGINAL_URL_FILTER = filtered.url_is_editorial_or_decorative
_ALLOWED_IMAGES = set()


def _clean(value):
    return v7.display_clean(value)


def fetch_article_strict(url, fallback):
    """Use only images that passed the article's editorial/decorative filter.

    V8 previously did a second loose page/media-library scan after the strict fetch.
    That could re-introduce team portraits. V12 intentionally does not do that.
    """
    global _ALLOWED_IMAGES
    text, images = filtered.fetch_article_filtered(url, fallback)
    v11._ARTICLE_TEXT = _clean(text)
    _ALLOWED_IMAGES = {str(x).strip() for x in images if str(x).strip()}
    return text, list(_ALLOWED_IMAGES)


def strict_url_filter(image_url):
    url = _clean(image_url)
    if not url:
        return True
    if _ORIGINAL_URL_FILTER(url):
        return True
    # Once the article has been parsed, accept only URLs returned by the strict
    # DOM filter. This also blocks old job-level/featured URLs if they point to
    # author portraits that were not accepted by the page parser.
    if _ALLOWED_IMAGES and url not in _ALLOWED_IMAGES:
        return True
    return False


def _canvas():
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def _blue_gradient_panel(im, box, radius=38, alpha=215):
    """Blue -> deep-navy panel used by the live YouTube overlays."""
    x0, y0, x1, y1 = [int(v) for v in box]
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    grad = Image.new('RGBA', (w, 1), (0, 0, 0, 0))
    px = grad.load()
    left = (28, 124, 226, alpha)
    mid = (13, 70, 157, alpha)
    right = (4, 18, 54, alpha)
    for x in range(w):
        t = x / max(1, w - 1)
        if t < 0.55:
            u = t / 0.55
            a, b = left, mid
        else:
            u = (t - 0.55) / 0.45
            a, b = mid, right
        px[x, 0] = tuple(int(a[i] + (b[i] - a[i]) * u) for i in range(4))
    grad = grad.resize((w, h))
    mask = Image.new('L', (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    im.paste(grad, (x0, y0), mask)


def safe_intro_overlay(title, domain, out):
    """Keep the lower 300px free for YouTube captions/player UI."""
    im = _canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)

    box = (65, 70, 1080, 720)
    _blue_gradient_panel(im, box, radius=42, alpha=224)
    d.rounded_rectangle((65, 70, 88, 720), radius=10, fill=(42, 207, 246, 255))
    d.rounded_rectangle((132, 125, 550, 195), radius=20, fill=(42, 207, 246, 248))
    cfont, clines = v7.strict_fit(d, cat, 350, 1, 31, 23, True)
    d.text((160, 143), clines[0], font=cfont, fill=(3, 16, 30, 255))

    tfont, lines = v7.strict_fit(d, _clean(title), 830, 5, 67, 38, True)
    line_h = int(getattr(tfont, 'size', 58) * 1.14)
    y = 255
    for line in lines:
        d.text((138, y), line, font=tfont, fill='white')
        y += line_h

    d.text((138, 635), 'Kurz erklärt · klar · direkt zum Beitrag', font=v5.font(27, False), fill=(225, 237, 246, 255))
    d.text((138, 680), domain, font=v5.font(25, True), fill=(103, 221, 255, 255))
    im.save(out)


def safe_content_overlay(title, heading, pts, domain, idx, total, out, compact=False):
    """Subtitle-safe content card: all important text stays in the upper 2/3."""
    if compact:
        return safe_minimal_overlay('', domain, idx, total, out, idx)

    statement = ''
    for p in pts or []:
        units = v11.v10.standalone_units(p)
        if units:
            statement = v11.v10.best_statement(' '.join(units))
            if statement:
                break
    if not statement:
        statement = 'Die wichtigsten Schritte und Details findest du im vollständigen Ratgeber.'

    heading = v11.v10.semantic_heading(statement, idx, total)
    im = _canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)

    if idx % 2:
        box = (70, 85, 955, 710)
        tx = 135
    else:
        box = (965, 85, 1850, 710)
        tx = 1030

    _blue_gradient_panel(im, box, radius=38, alpha=211)
    d.rounded_rectangle((box[0], box[1], box[0] + 20, box[3]), radius=10, fill=(42, 207, 246, 250))
    d.rounded_rectangle((tx, 135, tx + 360, 195), radius=18, fill=(42, 207, 246, 246))
    cfont, clines = v7.strict_fit(d, cat, 305, 1, 27, 22, True)
    d.text((tx + 26, 149), clines[0], font=cfont, fill=(4, 15, 28, 255))
    d.text((box[2] - 65, 151), f'{idx}/{total}', font=v5.font(25, True), fill=(115, 224, 255, 255), anchor='ra')

    hfont, hlines = v7.strict_fit(d, heading, 700, 2, 50, 38, True)
    y = 245
    for line in hlines:
        d.text((tx, y), line, font=hfont, fill='white')
        y += int(getattr(hfont, 'size', 46) * 1.16)

    y += 26
    pfont, plines = v7.strict_fit(d, statement, 700, 5, 37, 27, False)
    for line in plines:
        d.text((tx, y), line, font=pfont, fill=(239, 245, 250, 255))
        y += int(getattr(pfont, 'size', 33) * 1.27)

    d.text((tx, 655), domain, font=v5.font(24, True), fill=(198, 217, 232, 255))
    im.save(out)


def safe_minimal_overlay(text, domain, idx, total, out, variant=0):
    """Small transition badge at the top; never place it in caption territory."""
    im = _canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)
    if variant % 2:
        box = (1250, 80, 1835, 220)
        tx = 1300
    else:
        box = (85, 80, 670, 220)
        tx = 135
    _blue_gradient_panel(im, box, radius=28, alpha=198)
    d.rounded_rectangle((box[0], box[1], box[0] + 18, box[3]), radius=9, fill=(42, 207, 246, 245))
    d.text((tx, 110), cat, font=v5.font(27, True), fill=(115, 225, 255, 255))
    d.text((tx, 158), 'MS Ratgeber', font=v5.font(24, False), fill=(233, 241, 248, 255))
    d.text((box[2] - 34, 158), f'{idx}/{total}', font=v5.font(23, True), fill=(200, 220, 235, 255), anchor='ra')
    im.save(out)


def safe_cta_overlay(article_url, domain, out):
    """Keep next-video/CTA information above the YouTube subtitle safe zone."""
    im = _canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    next_title = _clean(v9._CURRENT_JOB.get('next_video_title', ''))
    next_url = _clean(v9._CURRENT_JOB.get('next_video_url', ''))

    box = (135, 70, 1785, 715)
    _blue_gradient_panel(im, box, radius=48, alpha=231)
    d.rounded_rectangle((135, 70, 160, 715), radius=10, fill=(42, 207, 246, 255))

    if next_title and next_url:
        d.rounded_rectangle((225, 135, 610, 205), radius=21, fill=(42, 207, 246, 248))
        d.text((265, 151), 'ALS NÄCHSTES', font=v5.font(29, True), fill=(3, 15, 28, 255))
        hfont, lines = v7.strict_fit(d, next_title, 1360, 4, 64, 40, True)
        y = 275
        for line in lines:
            d.text((225, y), line, font=hfont, fill='white')
            y += int(getattr(hfont, 'size', 56) * 1.13)
        d.text((225, 620), 'Passendes nächstes Video direkt im MS-Ratgeber-Kanal.', font=v5.font(29, False), fill=(226, 238, 248, 255))
    else:
        d.rounded_rectangle((225, 135, 700, 205), radius=21, fill=(42, 207, 246, 248))
        d.text((265, 151), 'DIREKT ZUM RATGEBER', font=v5.font(28, True), fill=(3, 15, 28, 255))
        d.text((225, 285), 'Alle Schritte & Details', font=v5.font(68, True), fill='white')
        d.text((225, 405), 'Den vollständigen Beitrag findest du über den Link in der Beschreibung.', font=v5.font(31, False), fill=(226, 238, 248, 255))
        ufont, ulines = v7.strict_fit(d, article_url, 1240, 2, 36, 27, True)
        y = 500
        for line in ulines:
            d.text((225, y), line, font=ufont, fill=(103, 221, 255, 255))
            y += int(getattr(ufont, 'size', 32) * 1.25)

    d.text((225, 670), domain, font=v5.font(25, True), fill=(195, 215, 230, 255))
    im.save(out)


def install_v12():
    v11.install_v11()

    # New MS family project.
    v5.CATEGORY_MAP['entsorgungshelfer.de'] = 'ENTSORGEN & RECYCLING'

    # Hard-stop the later loose image scan that could re-add editorial portraits.
    worker.fetch_article = fetch_article_strict
    filtered.url_is_editorial_or_decorative = strict_url_filter

    # YouTube caption-safe presentation layer.
    v5.make_intro_overlay = safe_intro_overlay
    v5.make_content_overlay = safe_content_overlay
    v6.make_flash_overlay = safe_minimal_overlay
    v6.make_cta_overlay_v6 = safe_cta_overlay


def main():
    install_v12()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

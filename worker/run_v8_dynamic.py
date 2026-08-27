import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote

from PIL import Image, ImageDraw

import render_and_upload_v2 as worker
import run_v4_dynamic as base
import run_v5_dynamic as v5
import run_v6_dynamic as v6
import run_v7_dynamic as v7

W, H = base.W, base.H
_ORIGINAL_FETCH = worker.fetch_article


def core_chunks(text, target=5):
    """Keep only 4-5 article core statements for visible editorial cards."""
    units = v7.complete_display_units(text, 20)
    if not units:
        return [v7.display_clean(text)] if v7.display_clean(text) else ['']

    wanted = 5 if len(units) >= 8 else min(4, len(units))
    wanted = max(1, wanted)
    picks = []
    n = len(units)
    for i in range(wanted):
        idx = round(i * (n - 1) / max(1, wanted - 1))
        unit = v7.display_clean(units[idx])
        if unit and unit not in picks:
            picks.append(unit)
    return picks[:5] or units[:4]


def minimal_visual_overlay(text, domain, idx, total, out, variant=0):
    """Image-led transition scene: no second paragraph competing with narration/captions."""
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)
    left = 90 if variant % 2 == 0 else 1260
    right = 660 if variant % 2 == 0 else 1830
    d.rounded_rectangle((left, 865, right, 1008), radius=28, fill=(4, 10, 22, 185))
    d.rounded_rectangle((left, 865, left + 18, 1008), radius=9, fill=(42, 207, 246, 245))
    d.text((left + 46, 895), cat, font=v5.font(27, True), fill=(115, 225, 255, 255))
    d.text((left + 46, 944), 'MS Ratgeber', font=v5.font(25, False), fill=(233, 241, 248, 255))
    d.text((right - 36, 944), f'{idx}/{total}', font=v5.font(24, True), fill=(200, 220, 235, 255), anchor='ra')
    im.save(out)


def calmer_content_overlay(title, heading, pts, domain, idx, total, out, compact=False):
    """Main editorial card = one core statement. Compact transition cards stay image-led."""
    alt_headings = {'Kurz gesagt', 'Darauf kommt es an', 'Jetzt prüfen'}
    if compact and v7.display_clean(heading) in alt_headings:
        return minimal_visual_overlay('', domain, idx, total, out, idx)

    clean = []
    for p in pts or []:
        clean.extend(v7.complete_display_units(p, 18))
    statement = clean[0] if clean else ''

    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)

    # Alternating smaller cards leave more of the image visible than V7.
    if idx % 2:
        box = (80, 160, 940, 880)
        tx = 145
    else:
        box = (980, 160, 1840, 880)
        tx = 1045

    d.rounded_rectangle(box, radius=38, fill=(4, 10, 22, 200))
    d.rounded_rectangle((box[0], box[1], box[0] + 20, box[3]), radius=10, fill=(42, 207, 246, 250))
    d.rounded_rectangle((tx, 215, tx + 360, 275), radius=18, fill=(42, 207, 246, 245))
    cfont, clines = v7.strict_fit(d, cat, 305, 1, 27, 22, True)
    d.text((tx + 26, 230), clines[0], font=cfont, fill=(4, 15, 28, 255))
    d.text((box[2] - 70, 232), f'{idx}/{total}', font=v5.font(26, True), fill=(115, 224, 255, 255), anchor='ra')

    hfont, hlines = v7.strict_fit(d, v7.display_clean(heading), 690, 2, 52, 39, True)
    y = 345
    for line in hlines:
        d.text((tx, y), line, font=hfont, fill='white')
        y += int(getattr(hfont, 'size', 48) * 1.18)

    y += 34
    pfont, plines = v7.strict_fit(d, v7.display_clean(statement), 690, 5, 38, 29, False)
    for line in plines:
        d.text((tx, y), line, font=pfont, fill=(239, 245, 250, 255))
        y += int(getattr(pfont, 'size', 34) * 1.30)

    d.text((tx, 815), domain, font=v5.font(25, True), fill=(198, 217, 232, 255))
    im.save(out)


def stronger_motion_filter(mode, dur):
    """A little more motion than V7, still slow enough for calm explainer videos."""
    variants = [
        ("iw/2-(iw/zoom/2)+sin(on/24)*72", "ih/2-(ih/zoom/2)+cos(on/33)*38", "min(zoom+0.00115,1.27)"),
        ("iw/2-(iw/zoom/2)-sin(on/28)*78", "ih/2-(ih/zoom/2)+sin(on/39)*40", "min(zoom+0.00108,1.26)"),
        ("iw/2-(iw/zoom/2)+cos(on/30)*70", "ih/2-(ih/zoom/2)-sin(on/32)*42", "min(zoom+0.00122,1.28)"),
        ("iw/2-(iw/zoom/2)-cos(on/25)*76", "ih/2-(ih/zoom/2)-cos(on/37)*36", "min(zoom+0.00110,1.265)"),
        ("iw/2-(iw/zoom/2)+sin(on/35)*64", "ih/2-(ih/zoom/2)-cos(on/27)*46", "min(zoom+0.00120,1.275)"),
        ("iw/2-(iw/zoom/2)-sin(on/31)*68", "ih/2-(ih/zoom/2)+cos(on/29)*44", "min(zoom+0.00112,1.27)"),
    ]
    x, y, z = variants[mode % len(variants)]
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps=30"


def fetch_article_with_more_images(url, fallback):
    """Keep article text logic, but collect more usable same-page images and optional WP media."""
    text, imgs = _ORIGINAL_FETCH(url, fallback)
    seen = list(imgs or [])
    try:
        r = worker.requests.get(url, timeout=22, headers={'User-Agent': 'Mozilla/5.0 (compatible; MS-Ratgeber-V8/1.0)'})
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, 'html.parser')
        root = soup.find('article') or soup.find('main') or soup.body
        if root:
            for im in root.find_all('img'):
                candidates = [im.get('data-src'), im.get('src')]
                srcset = im.get('srcset') or im.get('data-srcset')
                if srcset:
                    parts = [x.strip().split(' ')[0] for x in srcset.split(',') if x.strip()]
                    if parts:
                        candidates.insert(0, parts[-1])
                for src in candidates:
                    if not src:
                        continue
                    u = urljoin(url, src)
                    if u.startswith('http') and u not in seen:
                        seen.append(u)
                if len(seen) >= 18:
                    break

        # Optional: use matching images from the site's public WP media library when available.
        if len(seen) < 12:
            parsed = urlparse(url)
            slug_words = [w for w in re.split(r'[-_/]+', parsed.path) if len(w) >= 5][-3:]
            for word in slug_words:
                api = f'{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/media?per_page=6&search={quote(word)}&orderby=date&order=desc'
                try:
                    mr = worker.requests.get(api, timeout=8, headers={'User-Agent': 'MS-Ratgeber-V8/1.0'})
                    if mr.status_code != 200:
                        continue
                    for item in mr.json() if isinstance(mr.json(), list) else []:
                        u = item.get('source_url') or ''
                        if u.startswith('http') and u not in seen:
                            seen.append(u)
                        if len(seen) >= 18:
                            break
                except Exception:
                    continue
                if len(seen) >= 18:
                    break
    except Exception as exc:
        print('V8 extra image scan warning:', repr(exc))
    return text, seen[:18]


def install_v8():
    v7.install_v7()
    # Only rendering/presentation changes. Upload, OAuth and job logic stay untouched.
    v6.lively_chunks = core_chunks
    v5.make_content_overlay = calmer_content_overlay
    v6.make_flash_overlay = minimal_visual_overlay
    v6.motion_filter = stronger_motion_filter
    worker.fetch_article = fetch_article_with_more_images


def main():
    install_v8()
    return v6.main()


if __name__ == '__main__':
    raise SystemExit(main())

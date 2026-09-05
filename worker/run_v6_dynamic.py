import html
import re
import subprocess
import tempfile
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw

import render_and_upload_v2 as worker
import run_v2_filtered as filtered
import run_v4_dynamic as base
import run_v5_dynamic as v5

W, H = base.W, base.H
_ORIGINAL_UPLOAD = v5._ORIGINAL_UPLOAD


def decode_entities(value):
    s = '' if value is None else str(value)
    for _ in range(4):
        new = html.unescape(s)
        if new == s:
            break
        s = new
    return s.replace('\u00a0', ' ')


def clean_text(value):
    return re.sub(r'\s+', ' ', decode_entities(value)).strip()


def clean_multiline(value):
    text = decode_entities(value).replace('\r\n', '\n').replace('\r', '\n')
    lines = [re.sub(r'[ \t]+', ' ', line).strip() for line in text.split('\n')]
    out = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append('')
            blank = True
    return '\n'.join(out).strip()


def clickable_url(value):
    return v5.clickable_url(clean_text(value))


def sanitize_job(job):
    data = dict(job or {})
    data['title'] = clean_text(data.get('title', ''))
    data['description'] = clean_multiline(data.get('description', ''))
    article_url = clickable_url(data.get('article_url', ''))
    if article_url:
        data['article_url'] = article_url
        data['short_url'] = article_url
        data['source_url'] = article_url
    return data


def description_body(original):
    kept = []
    for raw in clean_multiline(original).splitlines():
        line = raw.strip()
        if not line:
            if kept and kept[-1] != '':
                kept.append('')
            continue
        low = line.casefold()
        if re.search(r'https?://', line, re.I):
            continue
        if low.startswith((
            'vollständiger ratgeber', 'vollstaendiger ratgeber',
            'vollständige anleitung', 'vollstaendige anleitung',
            'weitere hilfreiche ratgeber', 'ms ratgeber –', 'ms ratgeber -',
        )):
            continue
        if 'link oben' in low or 'link ganz oben' in low:
            continue
        if line.startswith(('👉', '▶', '►', '🔗')):
            continue
        kept.append(line)
    while kept and kept[-1] == '':
        kept.pop()
    return '\n'.join(kept).strip()


def upload_youtube_v6(video, job):
    enriched = sanitize_job(job)
    article_url = clickable_url(enriched.get('article_url', ''))
    domain = worker.domain_label(article_url) if article_url else ''
    home_url = f'https://{domain}/' if domain and '.' in domain else ''
    body = description_body(enriched.get('description', ''))

    parts = []
    if article_url:
        parts.extend(['🔗 DIREKT ZUM VOLLSTÄNDIGEN RATGEBER:', article_url, ''])
    if body:
        parts.extend([body, ''])
    if home_url and home_url != article_url:
        parts.extend(['Weitere hilfreiche Ratgeber:', home_url, ''])
    parts.append('MS Ratgeber – verständlich erklärt und direkt zur ausführlichen Anleitung.')

    enriched['description'] = '\n'.join(parts).strip()[:5000]
    return _ORIGINAL_UPLOAD(video, enriched)


def micro_units(text):
    text = clean_text(text)
    units = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        sentence = clean_text(sentence)
        if not sentence:
            continue
        clauses = [clean_text(x) for x in re.split(r'(?<=[,;:])\s+', sentence) if clean_text(x)]
        if len(clauses) == 1 and len(sentence.split()) > 24:
            words = sentence.split()
            clauses = [' '.join(words[i:i + 16]) for i in range(0, len(words), 16)]
        for clause in clauses:
            words = clause.split()
            if len(words) > 20:
                for i in range(0, len(words), 15):
                    part = ' '.join(words[i:i + 15]).strip()
                    if part:
                        units.append(part)
            else:
                units.append(clause)
    return units or ([text] if text else [])


def lively_chunks(text, target):
    units = micro_units(text)
    if not units:
        return ['']
    target = max(1, min(int(target), len(units)))
    chunks = []
    n = len(units)
    for i in range(target):
        a = round(i * n / target)
        b = round((i + 1) * n / target)
        part = clean_text(' '.join(units[a:b]))
        if part:
            chunks.append(part)
    return chunks or [clean_text(text)]


def flash_phrase(text, max_words=11):
    pts = base.bullets(text, 1, 110)
    phrase = clean_text(pts[0] if pts else text)
    words = phrase.split()
    if len(words) > max_words:
        phrase = ' '.join(words[:max_words]).rstrip('.,;:') + ' …'
    return phrase


def make_flash_overlay(text, domain, idx, total, out, variant=0):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    cat = v5.category_label(domain)
    phrase = flash_phrase(text)

    if variant % 3 == 0:
        box = (235, 230, 1685, 845)
        text_x, text_y = 330, 415
        label = 'WICHTIG'
    elif variant % 3 == 1:
        box = (110, 250, 1450, 900)
        text_x, text_y = 205, 450
        label = 'KURZ GESAGT'
    else:
        box = (470, 175, 1810, 855)
        text_x, text_y = 570, 385
        label = 'NÄCHSTER SCHRITT'

    d.rounded_rectangle(box, radius=48, fill=(4, 10, 22, 218))
    d.rounded_rectangle((box[0], box[1], box[0] + 22, box[3]), radius=10, fill=(42, 207, 246, 255))
    d.rounded_rectangle((text_x, box[1] + 72, text_x + 410, box[1] + 140), radius=21, fill=(42, 207, 246, 248))
    d.text((text_x + 34, box[1] + 87), label, font=v5.font(28, True), fill=(3, 16, 30, 255))

    fnt, lines = v5.fit_text(d, phrase, box[2] - text_x - 130, 5, 72, 40, 2, True)
    line_h = int(getattr(fnt, 'size', 60) * 1.17)
    y = text_y
    for line in lines[:5]:
        d.text((text_x + 4, y + 4), line, font=fnt, fill=(0, 0, 0, 145))
        d.text((text_x, y), line, font=fnt, fill='white')
        y += line_h

    d.text((box[0] + 95, box[3] - 90), cat, font=v5.font(27, True), fill=(103, 221, 255, 255))
    d.text((box[2] - 95, box[3] - 90), f'{idx}/{total}', font=v5.font(27, True), fill=(205, 223, 237, 255), anchor='ra')
    im.save(out)


def make_cta_overlay_v6(article_url, domain, out):
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((145, 180, 1775, 900), radius=54, fill=(4, 10, 22, 229))
    d.rounded_rectangle((145, 180, 169, 900), radius=10, fill=(42, 207, 246, 255))
    d.rounded_rectangle((240, 255, 690, 326), radius=21, fill=(42, 207, 246, 248))
    d.text((278, 272), 'DIREKT ZUM RATGEBER', font=v5.font(29, True), fill=(3, 15, 28, 255))
    d.text((240, 385), 'Alle Schritte & Details', font=v5.font(70, True), fill='white')
    d.text((240, 485), 'Öffne den direkten Beitragslink in der Beschreibung', font=v5.font(33, False), fill=(226, 238, 248, 255))

    link_font, link_lines = v5.fit_text(d, article_url, 1050, 3, 39, 27, 1, True)
    y = 565
    for line in link_lines[:3]:
        d.text((240, y), line, font=link_font, fill=(96, 222, 255, 255))
        y += int(getattr(link_font, 'size', 36) * 1.28)

    try:
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
        qr.add_data(article_url)
        qr.make(fit=True)
        qimg = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        qimg = qimg.resize((260, 260), Image.Resampling.NEAREST)
        im.paste(qimg.convert('RGBA'), (1435, 455))
        d.rounded_rectangle((1420, 440, 1710, 730), radius=24, outline=(255, 255, 255, 170), width=4)
        d.text((1565, 755), 'QR ZUM BEITRAG', font=v5.font(25, True), fill=(225, 238, 248, 255), anchor='ma')
    except Exception as exc:
        print('QR warning:', repr(exc))

    d.text((240, 820), domain, font=v5.font(29, True), fill=(195, 215, 230, 255))
    im.save(out)


def motion_filter(mode, dur):
    variants = [
        ("iw/2-(iw/zoom/2)+sin(on/22)*46", "ih/2-(ih/zoom/2)+cos(on/31)*26", "min(zoom+0.00092,1.20)"),
        ("iw/2-(iw/zoom/2)-sin(on/25)*52", "ih/2-(ih/zoom/2)+sin(on/36)*28", "min(zoom+0.00084,1.19)"),
        ("iw/2-(iw/zoom/2)+cos(on/27)*44", "ih/2-(ih/zoom/2)-sin(on/30)*30", "min(zoom+0.00098,1.21)"),
        ("iw/2-(iw/zoom/2)-cos(on/23)*50", "ih/2-(ih/zoom/2)-cos(on/35)*25", "min(zoom+0.00088,1.195)"),
        ("iw/2-(iw/zoom/2)+sin(on/33)*39", "ih/2-(ih/zoom/2)-cos(on/24)*34", "min(zoom+0.00102,1.22)"),
        ("iw/2-(iw/zoom/2)-sin(on/29)*43", "ih/2-(ih/zoom/2)+cos(on/26)*31", "min(zoom+0.00095,1.205)"),
        ("iw/2-(iw/zoom/2)+cos(on/21)*55", "ih/2-(ih/zoom/2)+sin(on/34)*22", "min(zoom+0.00086,1.19)"),
        ("iw/2-(iw/zoom/2)-cos(on/31)*41", "ih/2-(ih/zoom/2)-sin(on/23)*35", "min(zoom+0.00100,1.215)"),
    ]
    x, y, z = variants[mode % len(variants)]
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps=30"


def render_motion_clip(bg, overlay, out, dur, mode=0):
    vf = motion_filter(mode, dur)
    fade_out_start = max(0.25, float(dur) - 0.22)
    if mode % 4 == 0:
        ox, oy = "if(lt(t,0.32),70*(1-t/0.32),0)", "0"
    elif mode % 4 == 1:
        ox, oy = "if(lt(t,0.32),-70*(1-t/0.32),0)", "0"
    elif mode % 4 == 2:
        ox, oy = "0", "if(lt(t,0.30),40*(1-t/0.30),0)"
    else:
        ox, oy = "0", "if(lt(t,0.30),-40*(1-t/0.30),0)"

    fc = (
        f"[0:v]scale=2520:1418:force_original_aspect_ratio=increase,crop=2520:1418,"
        f"eq=contrast=1.065:saturation=1.12,unsharp=5:5:0.35:5:5:0.0,{vf}[m];"
        f"[1:v]format=rgba,fade=t=in:st=0:d=0.22:alpha=1,"
        f"fade=t=out:st={fade_out_start:.3f}:d=0.20:alpha=1[ov];"
        f"[m][ov]overlay=x='{ox}':y='{oy}':eval=frame:format=auto,format=yuv420p[v]"
    )
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', str(bg), '-loop', '1', '-i', str(overlay),
        '-t', f'{dur:.3f}', '-filter_complex', fc, '-map', '[v]', '-an', '-r', '30',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', str(out)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    worker.clean_text = clean_text
    v5.install_v5()
    worker.clean_text = clean_text
    worker.upload_youtube = upload_youtube_v6

    if not worker.WORKER_URL or not worker.SECRET:
        print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen; nichts zu tun.')
        return 0

    r = worker.requests.get(worker.WORKER_URL, headers=worker.HEAD, timeout=30)
    r.raise_for_status()
    raw_job = r.json().get('job')
    if not raw_job:
        print('Kein YouTube-Job in der Queue.')
        return 0
    job = sanitize_job(raw_job)

    jid = job['id']
    complete_url = job['complete_url']

    try:
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            text, imgs = worker.fetch_article(job['article_url'], job.get('description', ''))
            text = clean_text(text)
            narration = v5.build_narration(job['title'], text)
            worker.synthesize_voice(narration, td / 'voice.wav', td)
            audio_dur = worker.ffprobe_duration(td / 'voice.wav')

            domain = worker.domain_label(job.get('article_url', ''))
            article_url = clickable_url(job.get('article_url', ''))

            candidate_urls = []
            featured = job.get('image_url', '')
            if featured and not filtered.url_is_editorial_or_decorative(featured):
                candidate_urls.append(featured)
            for u in imgs:
                if u and u not in candidate_urls and not filtered.url_is_editorial_or_decorative(u):
                    candidate_urls.append(u)

            raw_paths = []
            for i, u in enumerate(candidate_urls):
                p = td / f'raw_{i:02d}.img'
                if worker.download_image(u, p):
                    raw_paths.append(p)
                if len(raw_paths) >= 12:
                    break
            raw_paths = base.valid_images(raw_paths)

            if not raw_paths:
                fallback = td / 'fallback.jpg'
                Image.new('RGB', (W, H), (16, 31, 52)).save(fallback)
                raw_paths = [fallback]

            bgs = []
            for i, p in enumerate(raw_paths[:10]):
                out = td / f'bg_{i:02d}.jpg'
                try:
                    base.prepare_bg(p, out)
                    bgs.append(out)
                except Exception:
                    continue
            if not bgs:
                fallback = td / 'fallback2.jpg'
                Image.new('RGB', (W, H), (16, 31, 52)).save(fallback)
                bgs = [fallback]

            intro_dur = min(4.0, max(2.8, audio_dur * 0.035))
            cta_dur = min(7.0, max(5.0, audio_dur * 0.055))
            remaining = max(25.0, audio_dur - intro_dur - cta_dur)
            target_main = max(10, min(28, int(round(remaining / 8.8))))
            cs = lively_chunks(text, target_main)

            scene_defs = []
            for i, ch in enumerate(cs):
                scene_defs.append(('main', i, ch, 1.0))
                if i < len(cs) - 1:
                    scene_defs.append(('alt', i, ch, 0.68))

            weight_sum = sum(x[3] for x in scene_defs) or 1.0
            unit_dur = remaining / weight_sum

            clips = []
            intro_ov = td / 'intro.png'
            v5.make_intro_overlay(job['title'], domain, intro_ov)
            intro_clip = td / 'clip_000.mp4'
            render_motion_clip(bgs[0], intro_ov, intro_clip, intro_dur, 0)
            clips.append(intro_clip)

            seq = 1
            for kind, i, ch, weight in scene_defs:
                dur = max(2.2, weight * unit_dur)
                bg = bgs[(i + (1 if kind == 'alt' else 0)) % len(bgs)]
                out_ov = td / f'ov_{seq:03d}.png'

                if kind == 'main':
                    v5.make_content_overlay(
                        job['title'], base.HEADINGS[i % len(base.HEADINGS)], base.bullets(ch),
                        domain, i + 1, len(cs), out_ov, (i % 4 == 3),
                    )
                elif i % 3 == 0:
                    make_flash_overlay(ch, domain, i + 1, len(cs), out_ov, i)
                else:
                    heading = ('Kurz gesagt', 'Darauf kommt es an', 'Jetzt prüfen')[i % 3]
                    one = base.bullets(ch, 1, 86)
                    v5.make_content_overlay(
                        job['title'], heading, [one[0] if one else flash_phrase(ch)],
                        domain, i + 1, len(cs), out_ov, True,
                    )

                clip = td / f'clip_{seq:03d}.mp4'
                render_motion_clip(bg, out_ov, clip, dur, seq)
                clips.append(clip)
                seq += 1

            cta_ov = td / 'cta.png'
            make_cta_overlay_v6(article_url, domain, cta_ov)
            cta_clip = td / f'clip_{seq:03d}.mp4'
            render_motion_clip(bgs[-1], cta_ov, cta_clip, cta_dur, seq)
            clips.append(cta_clip)

            listing = td / 'clips.txt'
            listing.write_text(
                ''.join("file '%s'\n" % str(c).replace("'", "'\\''") for c in clips),
                encoding='utf-8',
            )
            silent = td / 'silent.mp4'
            subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(silent)],
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )

            video = td / 'video.mp4'
            subprocess.run([
                'ffmpeg', '-y', '-i', str(silent), '-i', str(td / 'voice.wav'),
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy',
                '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '160k',
                '-shortest', '-movflags', '+faststart', str(video),
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            thumb = td / 'youtube-thumbnail.jpg'
            v5.make_thumbnail(bgs[0], job['title'], domain, thumb)

            vid = worker.upload_youtube(video, job)
            if not vid:
                raise RuntimeError('YouTube lieferte keine Video-ID')
            worker.set_thumbnail(vid, thumb, job['youtube_access_token'])
            print('Uploaded dynamic v6:', vid)
            worker.complete(complete_url, jid, True, video_id=vid)

    except Exception as exc:
        print('Worker v6 error:', repr(exc))
        worker.complete(complete_url, jid, False, error=str(exc)[:700])
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())

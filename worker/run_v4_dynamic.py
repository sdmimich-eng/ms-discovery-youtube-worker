import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

import render_and_upload_v2 as worker
import run_v2_filtered as filtered

worker.fetch_article = filtered.fetch_article_filtered

W, H = 1920, 1080
TW, TH = 1280, 720
HEADINGS = [
    'Das ist jetzt wichtig', 'Häufige Ursache', 'Das solltest du prüfen',
    'So gehst du vor', 'Der nächste Schritt', 'Wenn es noch nicht klappt',
    'Darauf achten', 'Kurz zusammengefasst'
]


def clean(s):
    return worker.clean_text(s)


def sentences(text):
    return [clean(x) for x in re.split(r'(?<=[.!?])\s+', clean(text)) if len(clean(x)) > 25]


def chunks(text, n=9):
    ss = sentences(text)
    if not ss:
        return [clean(text)]
    n = max(5, min(9, n))
    step = max(1, math.ceil(len(ss) / n))
    return [' '.join(ss[i:i + step]) for i in range(0, len(ss), step)][:n]


def bullets(text, limit=2, chars=105):
    out = []
    for s in sentences(text):
        s = re.sub(r'^[-–•]\s*', '', s)
        if len(s) > chars:
            s = s[:chars - 1].rsplit(' ', 1)[0] + '…'
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    if not out and clean(text):
        s = clean(text)
        out = [s[:chars - 1].rsplit(' ', 1)[0] + ('…' if len(s) >= chars else '')]
    return out


def topic_hook(title, max_words=6):
    t = clean(title)
    parts = re.split(r'\s+[–—|:]\s+|\s+-\s+', t)
    if parts:
        t = parts[0]
    ws = t.split()
    return ' '.join(ws[:max_words])


def build_narration(title, text):
    ss = sentences(text)
    body = ' '.join(ss)
    if len(body) > 3300:
        body = body[:3300].rsplit(' ', 1)[0]
    intro = f'{title}. Hier sind die wichtigsten Punkte und die sinnvollsten Schritte, die du jetzt prüfen kannst. '
    outro = ' Die ausführliche Anleitung mit allen Details und Aktualisierungen findest du über den Link ganz oben in der Videobeschreibung.'
    return clean(intro + body + outro)


def font(size, bold=False):
    p = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(p, size) if Path(p).exists() else ImageFont.load_default()


def wrap(draw, text, fnt, maxw):
    words = clean(text).split()
    lines, cur = [], ''
    for w in words:
        test = (cur + ' ' + w).strip()
        if draw.textbbox((0, 0), test, font=fnt)[2] <= maxw:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def domain_label(url):
    return worker.domain_label(url)


def transparent_canvas():
    return Image.new('RGBA', (W, H), (0, 0, 0, 0))


def make_intro_overlay(title, domain, out):
    im = transparent_canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((70, 100, 890, 940), radius=38, fill=(5, 12, 25, 205))
    d.rounded_rectangle((70, 100, 88, 940), radius=8, fill=(38, 197, 244, 255))
    d.rounded_rectangle((135, 155, 390, 215), radius=18, fill=(38, 197, 244, 235))
    d.text((160, 169), 'MS RATGEBER', font=font(25, True), fill=(5, 18, 32, 255))
    y = 280
    fh = font(68, True)
    for line in wrap(d, topic_hook(title, 8), fh, 650)[:5]:
        d.text((135, y), line, font=fh, fill='white')
        y += 80
    d.text((135, 815), 'Kurz erklärt · direkt zum Ratgeber', font=font(30, False), fill=(220, 235, 248, 255))
    d.text((135, 865), domain, font=font(28, True), fill=(95, 215, 255, 255))
    im.save(out)


def make_content_overlay(title, heading, pts, domain, idx, total, out, compact=False):
    im = transparent_canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    if compact:
        d.rounded_rectangle((80, 725, 1840, 1015), radius=30, fill=(5, 12, 25, 195))
        d.rounded_rectangle((80, 725, 98, 1015), radius=8, fill=(38, 197, 244, 255))
        d.text((135, 770), heading, font=font(48, True), fill='white')
        one = pts[0] if pts else ''
        for j, line in enumerate(wrap(d, one, font(34, False), 1500)[:2]):
            d.text((135, 840 + j * 44), line, font=font(34, False), fill=(235, 242, 248, 255))
    else:
        d.rounded_rectangle((80, 125, 890, 950), radius=34, fill=(5, 12, 25, 198))
        d.rounded_rectangle((80, 125, 98, 950), radius=8, fill=(38, 197, 244, 255))
        d.text((140, 165), f'{idx}/{total}', font=font(26, True), fill=(95, 215, 255, 255))
        y = 225
        for line in wrap(d, heading, font(57, True), 650)[:2]:
            d.text((140, y), line, font=font(57, True), fill='white')
            y += 67
        y += 28
        for p in pts[:2]:
            d.ellipse((142, y + 12, 160, y + 30), fill=(38, 197, 244, 255))
            for line in wrap(d, p, font(33, False), 620)[:3]:
                d.text((182, y), line, font=font(33, False), fill=(238, 244, 249, 255))
                y += 43
            y += 28
        d.text((140, 875), domain, font=font(27, True), fill=(190, 210, 228, 255))
    im.save(out)


def make_cta_overlay(short_url, domain, out):
    im = transparent_canvas()
    d = ImageDraw.Draw(im, 'RGBA')
    d.rounded_rectangle((220, 220, 1700, 860), radius=46, fill=(5, 12, 25, 215))
    d.text((300, 300), 'Alle Schritte & Details', font=font(74, True), fill='white')
    d.text((300, 415), 'Die vollständige Anleitung findest du hier:', font=font(36, False), fill=(225, 238, 248, 255))
    y = 505
    for line in wrap(d, short_url, font(47, True), 1250)[:2]:
        d.text((300, y), line, font=font(47, True), fill=(79, 216, 255, 255))
        y += 60
    d.text((300, 700), domain, font=font(31, True), fill=(195, 215, 230, 255))
    im.save(out)


def prepare_bg(src, out, size=(W, H)):
    if src and Path(src).exists():
        im = Image.open(src).convert('RGB')
        if im.width < 500 or im.height < 280:
            raise ValueError('image too small')
        ratio = max(size[0] / im.width, size[1] / im.height)
        im = im.resize((int(im.width * ratio), int(im.height * ratio)), Image.LANCZOS)
        left = max(0, (im.width - size[0]) // 2)
        top = max(0, (im.height - size[1]) // 2)
        im = im.crop((left, top, left + size[0], top + size[1]))
        im = ImageEnhance.Contrast(im).enhance(1.06)
        im = ImageEnhance.Color(im).enhance(1.05)
    else:
        im = Image.new('RGB', size, (15, 28, 48))
    im.save(out, quality=94)


def make_thumbnail(bg_path, title, domain, out):
    try:
        bg = Image.open(bg_path).convert('RGB') if bg_path and Path(bg_path).exists() else Image.new('RGB', (TW, TH), (12, 25, 45))
        ratio = max(TW / bg.width, TH / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        bg = bg.crop(((bg.width - TW)//2, (bg.height - TH)//2, (bg.width - TW)//2 + TW, (bg.height - TH)//2 + TH))
    except Exception:
        bg = Image.new('RGB', (TW, TH), (12, 25, 45))
    d = ImageDraw.Draw(bg, 'RGBA')
    for x in range(0, 720):
        alpha = int(225 * (1 - x / 760))
        d.rectangle((x, 0, x + 2, TH), fill=(4, 10, 20, max(0, alpha)))
    badge = 'FEHLER LÖSEN' if re.search(r'fehler|nicht|problem|geht nicht|verhindert', title, re.I) else 'SCHNELL ERKLÄRT'
    d.rounded_rectangle((45, 45, 325, 105), radius=16, fill=(38, 197, 244, 245))
    d.text((70, 59), badge, font=font(26, True), fill=(5, 18, 32))
    y = 150
    f = font(62, True)
    for line in wrap(d, topic_hook(title, 6), f, 575)[:5]:
        d.text((45, y), line, font=f, fill='white')
        y += 72
    d.rounded_rectangle((45, 610, 420, 678), radius=18, fill=(5, 15, 30, 210))
    d.text((70, 628), domain, font=font(27, True), fill=(110, 220, 255))
    bg.save(out, quality=94)


def motion_filter(mode, dur):
    if mode % 4 == 0:
        x = "iw/2-(iw/zoom/2)+sin(on/38)*24"
        y = "ih/2-(ih/zoom/2)+cos(on/55)*12"
        z = "min(zoom+0.00045,1.11)"
    elif mode % 4 == 1:
        x = "iw/2-(iw/zoom/2)-sin(on/42)*28"
        y = "ih/2-(ih/zoom/2)+sin(on/63)*12"
        z = "min(zoom+0.00038,1.095)"
    elif mode % 4 == 2:
        x = "iw/2-(iw/zoom/2)+cos(on/47)*20"
        y = "ih/2-(ih/zoom/2)-sin(on/58)*16"
        z = "min(zoom+0.00050,1.12)"
    else:
        x = "iw/2-(iw/zoom/2)-cos(on/45)*22"
        y = "ih/2-(ih/zoom/2)-cos(on/61)*12"
        z = "min(zoom+0.00042,1.105)"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={W}x{H}:fps=30"


def render_motion_clip(bg, overlay, out, dur, mode=0):
    vf = motion_filter(mode, dur)
    fc = f"[0:v]scale=2300:1294:force_original_aspect_ratio=increase,crop=2300:1294,{vf}[m];[1:v]format=rgba[ov];[m][ov]overlay=0:0:format=auto,format=yuv420p[v]"
    subprocess.run([
        'ffmpeg', '-y', '-loop', '1', '-i', str(bg), '-loop', '1', '-i', str(overlay),
        '-t', f'{dur:.3f}', '-filter_complex', fc, '-map', '[v]', '-an', '-r', '30',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-pix_fmt', 'yuv420p', str(out)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def valid_images(paths):
    good = []
    for p in paths:
        try:
            im = Image.open(p)
            if im.width >= 500 and im.height >= 280:
                good.append(p)
        except Exception:
            pass
    return good


def main():
    if not worker.WORKER_URL or not worker.SECRET:
        print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen; nichts zu tun.')
        return 0
    r = worker.requests.get(worker.WORKER_URL, headers=worker.HEAD, timeout=30)
    r.raise_for_status()
    job = r.json().get('job')
    if not job:
        print('Kein YouTube-Job in der Queue.')
        return 0

    jid = job['id']
    complete_url = job['complete_url']
    try:
        with tempfile.TemporaryDirectory() as td0:
            td = Path(td0)
            text, imgs = worker.fetch_article(job['article_url'], job.get('description', ''))
            narration = build_narration(job['title'], text)
            worker.synthesize_voice(narration, td / 'voice.wav', td)
            audio_dur = worker.ffprobe_duration(td / 'voice.wav')
            domain = domain_label(job.get('article_url', ''))
            short_url = job.get('short_url') or job.get('source_url') or job.get('article_url', '')

            raw_paths = []
            for i, u in enumerate([job.get('image_url', '')] + imgs):
                if not u:
                    continue
                p = td / f'raw_{i:02d}.img'
                if worker.download_image(u, p):
                    raw_paths.append(p)
                if len(raw_paths) >= 10:
                    break
            raw_paths = valid_images(raw_paths)

            if not raw_paths:
                fallback = td / 'fallback.jpg'
                Image.new('RGB', (W, H), (16, 31, 52)).save(fallback)
                raw_paths = [fallback]

            bgs = []
            for i, p in enumerate(raw_paths[:8]):
                out = td / f'bg_{i:02d}.jpg'
                try:
                    prepare_bg(p, out)
                    bgs.append(out)
                except Exception:
                    continue
            if not bgs:
                fallback = td / 'fallback2.jpg'
                Image.new('RGB', (W, H), (16, 31, 52)).save(fallback)
                bgs = [fallback]

            cs = chunks(text, 9)
            n_broll = min(4, max(1, len(cs)//2)) if len(bgs) > 1 else 1
            intro_dur = 5.5
            cta_dur = 7.0
            broll_each = 5.0
            content_time = max(35.0, audio_dur - intro_dur - cta_dur - n_broll * broll_each)
            main_each = max(7.0, content_time / max(1, len(cs)))

            clips = []
            intro_ov = td / 'intro.png'
            make_intro_overlay(job['title'], domain, intro_ov)
            intro_clip = td / 'clip_000.mp4'
            render_motion_clip(bgs[0], intro_ov, intro_clip, intro_dur, 0)
            clips.append(intro_clip)

            seq = 1
            broll_used = 0
            for i, ch in enumerate(cs):
                ov = td / f'ov_{i:02d}.png'
                compact = (i % 3 == 2)
                make_content_overlay(job['title'], HEADINGS[i % len(HEADINGS)], bullets(ch), domain, i+1, len(cs), ov, compact)
                clip = td / f'clip_{seq:03d}.mp4'
                render_motion_clip(bgs[i % len(bgs)], ov, clip, main_each, i+1)
                clips.append(clip)
                seq += 1

                if len(bgs) > 1 and broll_used < n_broll and i % 2 == 0:
                    bov = td / f'broll_{i:02d}.png'
                    one = bullets(ch, 1, 82)
                    make_content_overlay(job['title'], 'Im Detail', [one[0] if one else ''], domain, i+1, len(cs), bov, True)
                    bclip = td / f'clip_{seq:03d}.mp4'
                    render_motion_clip(bgs[(i + 1) % len(bgs)], bov, bclip, broll_each, i+3)
                    clips.append(bclip)
                    seq += 1
                    broll_used += 1

            cta_ov = td / 'cta.png'
            make_cta_overlay(short_url, domain, cta_ov)
            cta_clip = td / f'clip_{seq:03d}.mp4'
            render_motion_clip(bgs[-1], cta_ov, cta_clip, cta_dur, seq)
            clips.append(cta_clip)

            listing = td / 'clips.txt'
            listing.write_text(''.join("file '%s'\n" % str(c).replace("'", "'\\''") for c in clips), encoding='utf-8')
            silent = td / 'silent.mp4'
            subprocess.run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c', 'copy', str(silent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            video = td / 'video.mp4'
            subprocess.run([
                'ffmpeg', '-y', '-i', str(silent), '-i', str(td / 'voice.wav'),
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '144k',
                '-shortest', '-movflags', '+faststart', str(video)
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            thumb = td / 'youtube-thumbnail.jpg'
            make_thumbnail(bgs[0], job['title'], domain, thumb)

            vid = worker.upload_youtube(video, job)
            if not vid:
                raise RuntimeError('YouTube lieferte keine Video-ID')
            worker.set_thumbnail(vid, thumb, job['youtube_access_token'])
            print('Uploaded dynamic v4:', vid)
            worker.complete(complete_url, jid, True, video_id=vid)
    except Exception as e:
        print('Worker v4 error:', repr(e))
        worker.complete(complete_url, jid, False, error=str(e)[:700])
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

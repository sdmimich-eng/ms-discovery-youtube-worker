import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

SECRET = (os.environ.get('MSD_WORKER_SECRET') or '').strip()
CLAIM_FILE = Path(os.environ.get('MSD_CLAIM_FILE') or 'worker/claimed_job.json')
HEAD = {'X-MSD-Worker-Secret': SECRET, 'User-Agent': 'MS-Discovery-Instagram-Worker/1.0'}
W, H = 1080, 1920


def clean(s):
    return re.sub(r'\s+', ' ', str(s or '')).strip()


def font(size, bold=False):
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for p in candidates:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width, max_lines=5):
    words = clean(text).split()
    lines, cur = [], ''
    for word in words:
        trial = (cur + ' ' + word).strip()
        if draw.textbbox((0, 0), trial, font=fnt)[2] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
        if len(lines) >= max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and words:
        last = lines[-1]
        while draw.textbbox((0, 0), last + '…', font=fnt)[2] > max_width and ' ' in last:
            last = last.rsplit(' ', 1)[0]
        lines[-1] = last.rstrip('.,;:') + '…'
    return lines


def cover(im, w=W, h=H):
    im = im.convert('RGB')
    scale = max(w / im.width, h / im.height)
    nw, nh = int(im.width * scale), int(im.height * scale)
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    x, y = max(0, (nw - w) // 2), max(0, (nh - h) // 2)
    return im.crop((x, y, x + w, y + h))


def contain(im, w, h):
    im = im.convert('RGB')
    scale = min(w / im.width, h / im.height)
    nw, nh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def rounded_mask(size, radius):
    mask = Image.new('L', size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def download_image(url, out):
    r = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0 (MS Discovery Social Worker)'})
    r.raise_for_status()
    out.write_bytes(r.content)
    with Image.open(out) as im:
        im.verify()


def domain_label(job):
    d = clean(job.get('domain'))
    if d:
        return d
    try:
        return urlparse(job.get('article_url') or '').netloc.replace('www.', '')
    except Exception:
        return 'ms-programs.de'


def make_story(job, source, out):
    with Image.open(source) as src:
        bg = cover(src).filter(ImageFilter.GaussianBlur(16))
        bg = ImageEnhance.Brightness(bg).enhance(0.52)
        canvas = bg.copy()
        fg = contain(src, 980, 1070)
    fx = (W - fg.width) // 2
    fy = 150
    mask = rounded_mask(fg.size, 42)
    canvas.paste(fg, (fx, fy), mask)
    draw = ImageDraw.Draw(canvas, 'RGBA')
    draw.rounded_rectangle((55, 1260, 1025, 1815), radius=46, fill=(8, 17, 31, 218))
    title_font = font(58, True)
    small_font = font(32, False)
    brand_font = font(30, True)
    y = 1320
    for line in wrap(draw, job.get('title'), title_font, 875, 5):
        draw.text((105, y), line, font=title_font, fill='white')
        y += 76
    draw.text((105, 1740), 'Mehr dazu: ' + domain_label(job), font=small_font, fill=(220, 235, 255, 255))
    draw.rounded_rectangle((70, 65, 330, 125), radius=24, fill=(6, 21, 38, 205))
    draw.text((95, 79), 'MS-PROGRAMS', font=brand_font, fill=(255, 255, 255, 255))
    canvas.save(out, 'JPEG', quality=91, optimize=True)


def make_scene(job, source, kind):
    with Image.open(source) as src:
        bg = cover(src).filter(ImageFilter.GaussianBlur(14))
        bg = ImageEnhance.Brightness(bg).enhance(0.48)
        canvas = bg.copy()
        fg = contain(src, 1000, 1040)
    canvas.paste(fg, ((W - fg.width) // 2, 120), rounded_mask(fg.size, 34))
    draw = ImageDraw.Draw(canvas, 'RGBA')
    draw.rounded_rectangle((52, 1190, 1028, 1810), radius=44, fill=(7, 16, 29, 224))
    title_font = font(55, True)
    body_font = font(37, False)
    brand_font = font(29, True)
    if kind == 1:
        y = 1260
        for line in wrap(draw, job.get('title'), title_font, 870, 5):
            draw.text((105, y), line, font=title_font, fill='white')
            y += 72
        draw.text((105, 1740), 'Kurz erklärt', font=body_font, fill=(204, 229, 255, 255))
    elif kind == 2:
        draw.text((105, 1250), 'Darum geht es', font=title_font, fill='white')
        y = 1340
        desc = clean(job.get('description')) or clean(job.get('title'))
        for line in wrap(draw, desc, body_font, 870, 6):
            draw.text((105, y), line, font=body_font, fill=(245, 248, 252, 255))
            y += 57
    else:
        draw.text((105, 1280), 'Mehr erfahren', font=title_font, fill='white')
        dom = domain_label(job)
        y = 1400
        for line in wrap(draw, dom, font(50, True), 870, 3):
            draw.text((105, y), line, font=font(50, True), fill=(139, 215, 255, 255))
            y += 68
        draw.text((105, 1640), '#MSPrograms', font=body_font, fill='white')
    draw.rounded_rectangle((70, 65, 330, 125), radius=24, fill=(6, 21, 38, 205))
    draw.text((95, 79), 'MS-PROGRAMS', font=brand_font, fill='white')
    return canvas


def synth_music(path, duration, seed_text):
    sr = 44100
    n = int(sr * duration)
    seed = int((seed_text or '1')[:8], 16) if re.fullmatch(r'[0-9a-fA-F]+', (seed_text or '')[:8]) else 12345
    rng = random.Random(seed)
    progressions = [
        [261.63, 196.00, 220.00, 174.61],
        [220.00, 164.81, 196.00, 146.83],
        [293.66, 220.00, 246.94, 196.00],
    ]
    roots = progressions[seed % len(progressions)]
    buf = bytearray()
    for i in range(n):
        t = i / sr
        beat = t * 2.0
        bar = int(t / (duration / 4.0)) % 4
        root = roots[bar]
        triad = [root, root * 1.259921, root * 1.498307]
        tone = sum(math.sin(2 * math.pi * f * t) for f in triad) / 3.0
        bass = math.sin(2 * math.pi * (root / 2.0) * t)
        kick_phase = t % 0.5
        kick = math.sin(2 * math.pi * (72 - 35 * min(kick_phase / 0.12, 1)) * t) * math.exp(-kick_phase * 22) if kick_phase < 0.18 else 0.0
        hat_phase = t % 0.25
        noise = (rng.random() * 2 - 1) * math.exp(-hat_phase * 70) if hat_phase < 0.045 else 0.0
        fade = min(1.0, t / 0.7, (duration - t) / 0.9)
        val = (0.20 * tone + 0.16 * bass + 0.15 * kick + 0.035 * noise) * max(0.0, fade)
        sample = int(max(-1.0, min(1.0, val)) * 32767)
        buf += int(sample).to_bytes(2, 'little', signed=True) * 2
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(buf))


def make_reel(job, source, out, tmp):
    scenes = []
    for idx in (1, 2, 3):
        p = tmp / f'scene{idx}.jpg'
        make_scene(job, source, idx).save(p, 'JPEG', quality=91, optimize=True)
        scenes.append(p)
    duration = max(10, min(18, int(job.get('duration') or 14)))
    d1, d2 = 5, 5
    d3 = max(2, duration - d1 - d2)
    audio = tmp / 'music.wav'
    synth_music(audio, duration, str(job.get('music_seed') or '1'))
    filters = []
    frames = [d1 * 30, d2 * 30, d3 * 30]
    for i, fr in enumerate(frames):
        zoom = "min(zoom+0.00045,1.055)" if i != 1 else "min(zoom+0.00030,1.045)"
        filters.append(f'[{i}:v]scale=1080:1920,zoompan=z={zoom}:d={fr}:s=1080x1920:fps=30,setsar=1[v{i}]')
    filters.append('[v0][v1][v2]concat=n=3:v=1:a=0[v]')
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1', '-t', str(d1), '-i', str(scenes[0]),
        '-loop', '1', '-t', str(d2), '-i', str(scenes[1]),
        '-loop', '1', '-t', str(d3), '-i', str(scenes[2]),
        '-i', str(audio),
        '-filter_complex', ';'.join(filters),
        '-map', '[v]', '-map', '3:a',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '25', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '96k', '-movflags', '+faststart', '-shortest', str(out)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def complete(job, ok, asset=None, error=''):
    url = clean(job.get('complete_url'))
    if not url:
        raise RuntimeError('complete_url fehlt')
    data = {'job_id': clean(job.get('id')), 'ok': '1' if ok else '0', 'format': clean(job.get('format')), 'renderer': 'github-social-v1'}
    if error:
        data['error'] = clean(error)[:500]
    files = None
    fh = None
    try:
        if asset:
            mime = 'video/mp4' if str(asset).lower().endswith('.mp4') else 'image/jpeg'
            fh = open(asset, 'rb')
            files = {'asset': (Path(asset).name, fh, mime)}
        r = requests.post(url, headers=HEAD, data=data, files=files, timeout=90)
        if r.status_code >= 300:
            raise RuntimeError(f'Callback HTTP {r.status_code}: {r.text[:600]}')
        print('Callback:', r.text[:600])
    finally:
        if fh:
            fh.close()


def main():
    if not CLAIM_FILE.exists():
        print('Claim-Datei fehlt:', CLAIM_FILE)
        return 2
    job = json.loads(CLAIM_FILE.read_text(encoding='utf-8'))
    fmt = clean(job.get('format')).lower()
    if fmt not in ('story', 'reel'):
        print('Unbekanntes Social-Format:', fmt)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix='msd-social-') as td:
            tmp = Path(td)
            src = tmp / 'source.jpg'
            download_image(clean(job.get('image_url')), src)
            if fmt == 'story':
                out = tmp / 'story.jpg'
                make_story(job, src, out)
            else:
                out = tmp / 'reel.mp4'
                make_reel(job, src, out, tmp)
            print(fmt, 'gerendert:', out, out.stat().st_size, 'bytes')
            complete(job, True, out)
        return 0
    except Exception as e:
        print('Social worker failed:', repr(e))
        try:
            complete(job, False, None, str(e))
        except Exception as cb:
            print('Failure callback failed:', repr(cb))
        return 1


if __name__ == '__main__':
    sys.exit(main())

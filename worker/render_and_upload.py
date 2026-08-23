import os, sys, json, re, subprocess, tempfile, shutil, math, wave
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

WORKER_URL=os.environ.get('MSD_WORKER_URL','').strip()
SECRET=os.environ.get('MSD_WORKER_SECRET','').strip()
HEAD={'X-MSD-Worker-Secret':SECRET,'User-Agent':'MS-Discovery-YouTube-Worker/1.0'}

def complete(url, job_id, ok, **extra):
    try:
        requests.post(url, headers={**HEAD,'Content-Type':'application/json'}, json={'job_id':job_id,'ok':bool(ok),**extra}, timeout=30)
    except Exception as e:
        print('Callback failed:', e)

def clean_text(s):
    return re.sub(r'\s+',' ',s or '').strip()

def fetch_article(url, fallback):
    try:
        r=requests.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0 (compatible; MS-Ratgeber/1.0)'});r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        for t in soup(['script','style','nav','footer','header','aside','form']): t.decompose()
        root=soup.find('article') or soup.find('main') or soup.body
        paras=[]
        if root:
            for p in root.find_all(['p','li']):
                tx=clean_text(p.get_text(' ',strip=True))
                if len(tx)>=45 and not tx.lower().startswith(('werbung','anzeige')): paras.append(tx)
        text=' '.join(paras)
        if len(text)<500: text=fallback
        text=clean_text(text)[:6500]
        imgs=[]
        og=soup.find('meta',attrs={'property':'og:image'})
        if og and og.get('content'): imgs.append(urljoin(url,og['content']))
        if root:
            for im in root.find_all('img'):
                src=im.get('data-src') or im.get('src')
                if src:
                    u=urljoin(url,src)
                    if u.startswith('http') and u not in imgs: imgs.append(u)
                if len(imgs)>=6: break
        return text, imgs
    except Exception as e:
        print('Article fetch warning:',e)
        return clean_text(fallback), []

def sentence_chunks(text, n=6):
    sentences=re.split(r'(?<=[.!?])\s+',clean_text(text))
    sentences=[x for x in sentences if len(x)>25]
    if not sentences: return [text]
    target=max(1,math.ceil(len(sentences)/n));chunks=[]
    for i in range(0,len(sentences),target): chunks.append(' '.join(sentences[i:i+target]))
    return chunks[:n]

def download_image(url, out):
    try:
        r=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status();out.write_bytes(r.content)
        im=Image.open(out);im.verify();return True
    except Exception: return False

def font(size,bold=False):
    p='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(p,size) if Path(p).exists() else ImageFont.load_default()

def wrap(draw, text, f, maxw):
    words=text.split();lines=[];cur=''
    for w in words:
        t=(cur+' '+w).strip()
        if draw.textbbox((0,0),t,font=f)[2] <= maxw: cur=t
        else:
            if cur: lines.append(cur)
            cur=w
    if cur: lines.append(cur)
    return lines

def make_slide(bg_path, title, body, out, idx, total):
    W,H=1920,1080
    if bg_path and Path(bg_path).exists():
        im=Image.open(bg_path).convert('RGB');ratio=max(W/im.width,H/im.height);im=im.resize((int(im.width*ratio),int(im.height*ratio)));left=(im.width-W)//2;top=(im.height-H)//2;im=im.crop((left,top,left+W,top+H)).filter(ImageFilter.GaussianBlur(5));im=ImageEnhance.Brightness(im).enhance(.42)
    else: im=Image.new('RGB',(W,H),(20,30,48))
    dr=ImageDraw.Draw(im,'RGBA');dr.rounded_rectangle((120,120,1800,960),radius=34,fill=(8,15,28,185))
    ft=font(70,True);fb=font(43,False);fs=font(28,False);y=185
    for line in wrap(dr,title,ft,1500)[:3]: dr.text((190,y),line,font=ft,fill='white');y+=82
    y+=35;lines=wrap(dr,clean_text(body),fb,1500);maxlines=max(4,min(9,int((850-y)/55)))
    for line in lines[:maxlines]: dr.text((190,y),line,font=fb,fill=(235,240,247));y+=57
    dr.text((190,900),f'MS Ratgeber  •  {idx}/{total}',font=fs,fill=(190,205,225));im.save(out,quality=94)

def tts_chunks(text, max_chars=850):
    sentences=re.split(r'(?<=[.!?])\s+',clean_text(text));out=[];cur=''
    for sentence in sentences:
        if not sentence: continue
        test=(cur+' '+sentence).strip()
        if cur and len(test)>max_chars: out.append(cur);cur=sentence
        else: cur=test
    if cur: out.append(cur)
    return out or [clean_text(text)]

def synthesize_voice(text, out_wav, td):
    model=Path(__file__).resolve().parent/'voices'/'de_DE-thorsten-medium.onnx'
    try:
        from piper import PiperVoice, SynthesisConfig
        if not model.exists(): raise FileNotFoundError(str(model))
        voice=PiperVoice.load(str(model));parts=[];syn=SynthesisConfig(length_scale=1.04, noise_scale=0.62, noise_w_scale=0.78, normalize_audio=True)
        for i,chunk in enumerate(tts_chunks(text)):
            wavp=Path(td)/f'voice_{i:02d}.wav'
            with wave.open(str(wavp),'wb') as wf: voice.synthesize_wav(chunk,wf,syn_config=syn)
            parts.append(wavp)
        if len(parts)==1: shutil.copyfile(parts[0],out_wav)
        else:
            listing=Path(td)/'voice_concat.txt';listing.write_text(''.join("file '%s'\n"%str(x).replace("'","'\\''") for x in parts),encoding='utf-8')
            subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(listing),'-c:a','pcm_s16le',str(out_wav)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print('TTS: Piper de_DE-thorsten-medium');return
    except Exception as e: print('Piper TTS fallback:',repr(e))
    txt=Path(td)/'narration.txt';txt.write_text(text,encoding='utf-8');subprocess.run(['espeak-ng','-v','de','-s','152','-w',str(out_wav),'-f',str(txt)],check=True)

def build_narration(title, text):
    useful=clean_text(' '.join(sentence_chunks(text,7)))[:6000]
    return clean_text(f'{title}. In diesem Video schauen wir uns das Thema Schritt für Schritt an. '+useful+' Die vollständige Anleitung mit allen Details findest du über den Link ganz oben in der Videobeschreibung.')

def ffprobe_duration(path):
    x=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True).strip();return max(1.0,float(x))

def upload_youtube(video, job):
    token=job['youtube_access_token'];meta={'snippet':{'title':job['title'][:100],'description':job['description'][:5000],'categoryId':'26','defaultLanguage':'de'},'status':{'privacyStatus':job.get('privacy','public'),'selfDeclaredMadeForKids':False,'containsSyntheticMedia':bool(job.get('contains_synthetic_media',True))}}
    url='https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status';size=os.path.getsize(video)
    r=requests.post(url,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':str(size)},data=json.dumps(meta,ensure_ascii=False).encode(),timeout=30)
    if r.status_code not in (200,201): raise RuntimeError('YouTube init HTTP %s: %s'%(r.status_code,r.text[:500]))
    loc=r.headers.get('Location')
    if not loc: raise RuntimeError('YouTube resumable upload URL fehlt')
    with open(video,'rb') as f: up=requests.put(loc,headers={'Authorization':'Bearer '+token,'Content-Type':'video/mp4','Content-Length':str(size)},data=f,timeout=600)
    if up.status_code not in (200,201): raise RuntimeError('YouTube upload HTTP %s: %s'%(up.status_code,up.text[:800]))
    return up.json().get('id','')

def set_thumbnail(video_id, image_path, token):
    try:
        im=Image.open(image_path).convert('RGB');im.thumbnail((1280,720));canvas=Image.new('RGB',(1280,720),(20,30,48));canvas.paste(im,((1280-im.width)//2,(720-im.height)//2));thumb=Path(image_path).with_name('youtube-thumbnail.jpg');canvas.save(thumb,quality=91,optimize=True)
        raw=thumb.read_bytes();url='https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId='+video_id+'&uploadType=media';r=requests.post(url,headers={'Authorization':'Bearer '+token,'Content-Type':'image/jpeg','Content-Length':str(len(raw))},data=raw,timeout=60)
        print('Custom thumbnail set' if r.status_code in (200,201) else 'Thumbnail warning HTTP '+str(r.status_code))
    except Exception as e: print('Thumbnail warning:',repr(e))

def main():
    if not WORKER_URL or not SECRET: print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen; nichts zu tun.');return 0
    r=requests.get(WORKER_URL,headers=HEAD,timeout=30);r.raise_for_status();job=r.json().get('job')
    if not job: print('Kein YouTube-Job in der Queue.');return 0
    jid=job['id'];complete_url=job['complete_url']
    try:
        with tempfile.TemporaryDirectory() as td0:
            td=Path(td0);text,imgs=fetch_article(job['article_url'],job.get('description',''));narration=build_narration(job['title'],text);synthesize_voice(narration,td/'voice.wav',td);dur=ffprobe_duration(td/'voice.wav');bgs=[]
            for i,u in enumerate([job.get('image_url','')]+imgs):
                if u and download_image(u,td/f'img{i}.jpg'): bgs.append(td/f'img{i}.jpg')
                if len(bgs)>=6: break
            chunks=sentence_chunks(text,6);slides=[];total=max(3,len(chunks))
            for i in range(total):
                body=chunks[i] if i<len(chunks) else 'Mehr Details und die vollständige Anleitung findest du über den Link in der Videobeschreibung.';bg=bgs[i%len(bgs)] if bgs else None;out=td/f'slide{i:02d}.jpg';make_slide(bg,job['title'],body,out,i+1,total);slides.append(out)
            per=max(6.0,dur/len(slides));concat=td/'slides.txt'
            with concat.open('w',encoding='utf-8') as f:
                for sl in slides: f.write("file '%s'\nduration %.3f\n"%(str(sl).replace("'","'\\''"),per))
                f.write("file '%s'\n"%str(slides[-1]).replace("'","'\\''"))
            video=td/'video.mp4';subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(td/'voice.wav'),'-vf','scale=1920:1080,format=yuv420p','-r','30','-c:v','libx264','-preset','medium','-crf','22','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(video)],check=True)
            vid=upload_youtube(video,job)
            if not vid: raise RuntimeError('YouTube lieferte keine Video-ID')
            if slides: set_thumbnail(vid,slides[0],job['youtube_access_token'])
            print('Uploaded:',vid);complete(complete_url,jid,True,video_id=vid)
    except Exception as e:
        print('Worker error:',repr(e));complete(complete_url,jid,False,error=str(e)[:700]);return 1
    return 0

if __name__=='__main__': sys.exit(main())

import os, sys, json, re, subprocess, tempfile, shutil, math, wave
from pathlib import Path
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

WORKER_URL=os.environ.get('MSD_WORKER_URL','').strip()
SECRET=os.environ.get('MSD_WORKER_SECRET','').strip()
HEAD={'X-MSD-Worker-Secret':SECRET,'User-Agent':'MS-Discovery-YouTube-Worker/1.1'}
SLIDE_HEADINGS=['Kurz erklärt','Das steckt oft dahinter','Das solltest du prüfen','So gehst du vor','Wichtiger Zwischenschritt','Wenn es noch nicht klappt','Darauf solltest du achten','Die nächsten Schritte','Praktische Lösung','Zum Schluss']

def complete(url, job_id, ok, **extra):
    try:
        requests.post(url, headers={**HEAD,'Content-Type':'application/json'}, json={'job_id':job_id,'ok':bool(ok),**extra}, timeout=30)
    except Exception as e: print('Callback failed:',e)

def clean_text(s): return re.sub(r'\s+',' ',s or '').strip()

def fetch_article(url, fallback):
    try:
        r=requests.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0 (compatible; MS-Ratgeber/1.1)'});r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        for t in soup(['script','style','nav','footer','header','aside','form']): t.decompose()
        root=soup.find('article') or soup.find('main') or soup.body;paras=[]
        if root:
            for p in root.find_all(['p','li']):
                tx=clean_text(p.get_text(' ',strip=True))
                if len(tx)>=45 and not tx.lower().startswith(('werbung','anzeige')): paras.append(tx)
        text=clean_text(' '.join(paras))
        if len(text)<500:text=clean_text(fallback)
        text=text[:7000];imgs=[]
        og=soup.find('meta',attrs={'property':'og:image'})
        if og and og.get('content'):imgs.append(urljoin(url,og['content']))
        if root:
            for im in root.find_all('img'):
                src=im.get('data-src') or im.get('src')
                if src:
                    u=urljoin(url,src)
                    if u.startswith('http') and u not in imgs:imgs.append(u)
                if len(imgs)>=8:break
        return text,imgs
    except Exception as e:
        print('Article fetch warning:',e);return clean_text(fallback),[]

def sentences(text):
    return [clean_text(x) for x in re.split(r'(?<=[.!?])\s+',clean_text(text)) if len(clean_text(x))>25]

def sentence_chunks(text,n=10):
    s=sentences(text)
    if not s:return [clean_text(text)]
    target=max(1,math.ceil(len(s)/n));return [' '.join(s[i:i+target]) for i in range(0,len(s),target)][:n]

def slide_points(text,max_points=3):
    pts=[]
    for s in sentences(text):
        s=re.sub(r'^[-–•]\s*','',s)
        if len(s)>165:s=s[:162].rsplit(' ',1)[0]+'…'
        if s and s not in pts:pts.append(s)
        if len(pts)>=max_points:break
    if not pts and clean_text(text):pts=[clean_text(text)[:165]]
    return pts

def download_image(url,out):
    try:
        r=requests.get(url,timeout=20,headers={'User-Agent':'Mozilla/5.0'});r.raise_for_status();out.write_bytes(r.content)
        im=Image.open(out);im.verify();return True
    except Exception:return False

def font(size,bold=False):
    p='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    return ImageFont.truetype(p,size) if Path(p).exists() else ImageFont.load_default()

def wrap(draw,text,f,maxw):
    words=clean_text(text).split();lines=[];cur=''
    for w in words:
        t=(cur+' '+w).strip()
        if draw.textbbox((0,0),t,font=f)[2]<=maxw:cur=t
        else:
            if cur:lines.append(cur)
            cur=w
    if cur:lines.append(cur)
    return lines

def background(bg_path,W,H):
    if bg_path and Path(bg_path).exists():
        im=Image.open(bg_path).convert('RGB');ratio=max(W/im.width,H/im.height);im=im.resize((int(im.width*ratio),int(im.height*ratio)));left=(im.width-W)//2;top=(im.height-H)//2;im=im.crop((left,top,left+W,top+H)).filter(ImageFilter.GaussianBlur(3));return ImageEnhance.Brightness(im).enhance(.48)
    return Image.new('RGB',(W,H),(17,27,44))

def domain_label(url):
    try:return urlparse(url).netloc.replace('www.','')
    except Exception:return 'MS Ratgeber'

def make_slide(bg_path,video_title,heading,points,out,idx,total,domain):
    W,H=1920,1080;im=background(bg_path,W,H);dr=ImageDraw.Draw(im,'RGBA')
    dr.rectangle((0,0,W,H),fill=(4,10,20,70));dr.rounded_rectangle((105,105,1815,965),radius=38,fill=(8,15,28,196));dr.rounded_rectangle((105,105,128,965),radius=10,fill=(56,199,240,245))
    ftiny=font(30,True);fh=font(76,True);fb=font(43,False);ff=font(28,False)
    small=wrap(dr,video_title,ftiny,1510)[:2];y=150
    for line in small:dr.text((185,y),line,font=ftiny,fill=(190,210,230));y+=39
    y+=25
    for line in wrap(dr,heading,fh,1450)[:2]:dr.text((185,y),line,font=fh,fill='white');y+=88
    y+=28
    for p in points[:3]:
        dr.ellipse((190,y+14,210,y+34),fill=(56,199,240,255));x=235
        lines=wrap(dr,p,fb,1410)[:3]
        for line in lines:dr.text((x,y),line,font=fb,fill=(241,245,250));y+=54
        y+=26
        if y>850:break
    dr.text((185,910),domain,font=ff,fill=(190,205,225));dr.text((1600,910),f'{idx}/{total}',font=ff,fill=(190,205,225));im.save(out,quality=94)

def make_cta_slide(bg_path,title,short_url,out,idx,total,domain):
    W,H=1920,1080;im=background(bg_path,W,H);dr=ImageDraw.Draw(im,'RGBA');dr.rectangle((0,0,W,H),fill=(4,10,20,105));dr.rounded_rectangle((150,150,1770,930),radius=42,fill=(8,15,28,215))
    f1=font(82,True);f2=font(50,True);f3=font(37,False);y=230
    dr.text((220,y),'Vollständige Anleitung',font=f1,fill='white');y+=125
    dr.text((220,y),'Alle Schritte, Details und Aktualisierungen:',font=f3,fill=(225,235,245));y+=85
    for line in wrap(dr,short_url,f2,1450)[:2]:dr.text((220,y),line,font=f2,fill=(115,220,255));y+=68
    y+=55;dr.text((220,y),'Link steht auch ganz oben in der Videobeschreibung.',font=f3,fill=(225,235,245));dr.text((220,835),domain,font=f3,fill=(190,205,225));dr.text((1600,835),f'{idx}/{total}',font=f3,fill=(190,205,225));im.save(out,quality=94)

def thumbnail_hook(title):
    t=clean_text(title);parts=re.split(r'\s+[–—-]\s+',t)
    t=parts[0] if parts else t
    words=t.split()
    if len(words)>8:t=' '.join(words[:8])
    return t

def make_thumbnail(bg_path,title,domain,out):
    W,H=1280,720;im=background(bg_path,W,H);dr=ImageDraw.Draw(im,'RGBA');dr.rectangle((0,0,W,H),fill=(3,8,18,85));dr.rounded_rectangle((45,45,870,675),radius=36,fill=(5,12,24,205));dr.rounded_rectangle((45,45,70,675),radius=10,fill=(56,199,240,255))
    badge='FEHLER LÖSEN' if re.search(r'fehler|nicht|problem|geht nicht',title,re.I) else 'SCHNELL ERKLÄRT'
    dr.rounded_rectangle((105,95,425,155),radius=18,fill=(56,199,240,245));dr.text((130,108),badge,font=font(27,True),fill=(5,20,35))
    fh=font(61,True);y=205
    for line in wrap(dr,thumbnail_hook(title),fh,700)[:5]:dr.text((105,y),line,font=fh,fill='white');y+=72
    dr.text((105,610),domain,font=font(29,True),fill=(205,220,235));im.save(out,quality=93)

def tts_chunks(text,max_chars=850):
    out=[];cur=''
    for s in re.split(r'(?<=[.!?])\s+',clean_text(text)):
        if not s:continue
        test=(cur+' '+s).strip()
        if cur and len(test)>max_chars:out.append(cur);cur=s
        else:cur=test
    if cur:out.append(cur)
    return out or [clean_text(text)]

def synthesize_voice(text,out_wav,td):
    model=Path(__file__).resolve().parent/'voices'/'de_DE-thorsten-medium.onnx'
    try:
        from piper import PiperVoice,SynthesisConfig
        if not model.exists():raise FileNotFoundError(str(model))
        voice=PiperVoice.load(str(model));parts=[];syn=SynthesisConfig(length_scale=1.04,noise_scale=0.62,noise_w_scale=0.78,normalize_audio=True)
        for i,chunk in enumerate(tts_chunks(text)):
            wavp=Path(td)/f'voice_{i:02d}.wav'
            with wave.open(str(wavp),'wb') as wf:voice.synthesize_wav(chunk,wf,syn_config=syn)
            parts.append(wavp)
        if len(parts)==1:shutil.copyfile(parts[0],out_wav)
        else:
            listing=Path(td)/'voice_concat.txt';listing.write_text(''.join("file '%s'\n"%str(x).replace("'","'\\''") for x in parts),encoding='utf-8')
            subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(listing),'-c:a','pcm_s16le',str(out_wav)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        print('TTS: Piper de_DE-thorsten-medium');return
    except Exception as e:print('Piper TTS fallback:',repr(e))
    txt=Path(td)/'narration.txt';txt.write_text(text,encoding='utf-8');subprocess.run(['espeak-ng','-v','de','-s','152','-w',str(out_wav),'-f',str(txt)],check=True)

def build_narration(title,text):
    useful=clean_text(' '.join(sentence_chunks(text,9)))[:6100]
    return clean_text(f'{title}. In diesem Video schauen wir uns das Thema Schritt für Schritt an. '+useful+' Die vollständige Anleitung mit allen Details findest du über den Link ganz oben in der Videobeschreibung.')

def ffprobe_duration(path):
    x=subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',str(path)],text=True).strip();return max(1.0,float(x))

def upload_youtube(video,job):
    token=job['youtube_access_token'];meta={'snippet':{'title':job['title'][:100],'description':job['description'][:5000],'categoryId':'26','defaultLanguage':'de'},'status':{'privacyStatus':job.get('privacy','public'),'selfDeclaredMadeForKids':False,'containsSyntheticMedia':bool(job.get('contains_synthetic_media',True))}}
    url='https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status';size=os.path.getsize(video)
    r=requests.post(url,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':str(size)},data=json.dumps(meta,ensure_ascii=False).encode(),timeout=30)
    if r.status_code not in (200,201):raise RuntimeError('YouTube init HTTP %s: %s'%(r.status_code,r.text[:500]))
    loc=r.headers.get('Location')
    if not loc:raise RuntimeError('YouTube resumable upload URL fehlt')
    with open(video,'rb') as f:up=requests.put(loc,headers={'Authorization':'Bearer '+token,'Content-Type':'video/mp4','Content-Length':str(size)},data=f,timeout=600)
    if up.status_code not in (200,201):raise RuntimeError('YouTube upload HTTP %s: %s'%(up.status_code,up.text[:800]))
    return up.json().get('id','')

def set_thumbnail(video_id,image_path,token):
    try:
        raw=Path(image_path).read_bytes();url='https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId='+video_id+'&uploadType=media';r=requests.post(url,headers={'Authorization':'Bearer '+token,'Content-Type':'image/jpeg','Content-Length':str(len(raw))},data=raw,timeout=60)
        print('Custom thumbnail set' if r.status_code in (200,201) else 'Thumbnail warning HTTP '+str(r.status_code))
    except Exception as e:print('Thumbnail warning:',repr(e))

def main():
    if not WORKER_URL or not SECRET:print('MSD_WORKER_URL/MSD_WORKER_SECRET fehlen; nichts zu tun.');return 0
    r=requests.get(WORKER_URL,headers=HEAD,timeout=30);r.raise_for_status();job=r.json().get('job')
    if not job:print('Kein YouTube-Job in der Queue.');return 0
    jid=job['id'];complete_url=job['complete_url']
    try:
        with tempfile.TemporaryDirectory() as td0:
            td=Path(td0);text,imgs=fetch_article(job['article_url'],job.get('description',''));narration=build_narration(job['title'],text);synthesize_voice(narration,td/'voice.wav',td);dur=ffprobe_duration(td/'voice.wav');bgs=[]
            for i,u in enumerate([job.get('image_url','')]+imgs):
                if u and download_image(u,td/f'img{i}.jpg'):bgs.append(td/f'img{i}.jpg')
                if len(bgs)>=8:break
            chunks=sentence_chunks(text,10);domain=domain_label(job.get('article_url',''));short_url=job.get('short_url') or job.get('source_url') or job.get('article_url','');slides=[];total=len(chunks)+1
            for i,ch in enumerate(chunks):
                bg=bgs[i%len(bgs)] if bgs else None;out=td/f'slide{i:02d}.jpg';make_slide(bg,job['title'],SLIDE_HEADINGS[i%len(SLIDE_HEADINGS)],slide_points(ch),out,i+1,total,domain);slides.append(out)
            cta=td/f'slide{len(slides):02d}.jpg';make_cta_slide(bgs[-1] if bgs else None,job['title'],short_url,cta,total,total,domain);slides.append(cta)
            thumb=td/'youtube-thumbnail.jpg';make_thumbnail(bgs[0] if bgs else None,job['title'],domain,thumb)
            per=max(5.0,dur/max(1,len(slides)-.35));concat=td/'slides.txt'
            with concat.open('w',encoding='utf-8') as f:
                for sl in slides:f.write("file '%s'\nduration %.3f\n"%(str(sl).replace("'","'\\''"),per))
                f.write("file '%s'\n"%str(slides[-1]).replace("'","'\\''"))
            video=td/'video.mp4';subprocess.run(['ffmpeg','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(td/'voice.wav'),'-vf','scale=1920:1080,format=yuv420p','-r','30','-c:v','libx264','-preset','medium','-crf','22','-c:a','aac','-b:a','128k','-shortest','-movflags','+faststart',str(video)],check=True)
            vid=upload_youtube(video,job)
            if not vid:raise RuntimeError('YouTube lieferte keine Video-ID')
            set_thumbnail(vid,thumb,job['youtube_access_token']);print('Uploaded:',vid);complete(complete_url,jid,True,video_id=vid)
    except Exception as e:
        print('Worker error:',repr(e));complete(complete_url,jid,False,error=str(e)[:700]);return 1
    return 0

if __name__=='__main__':sys.exit(main())

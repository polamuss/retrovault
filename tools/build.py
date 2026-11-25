"""Build public RetroVault data. Run only on the maintainer/build machine, never in browsers.
The image input is a whitelist of local files that the publisher is entitled to redistribute.
No ROM downloads. No image search or bulk scraping.
"""
import argparse, concurrent.futures, hashlib, json, re, shutil, urllib.error, urllib.parse, urllib.request, unicodedata, xml.etree.ElementTree as ET, zipfile
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='https://raw.githubusercontent.com/libretro/libretro-database/master/'

def read_json(p): return json.loads(p.read_text(encoding='utf-8'))
def write_json(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
def norm(s): return ' '.join(re.sub(r'[^\w]+',' ',unicodedata.normalize('NFKD',s.casefold()),flags=re.UNICODE).split())
def valid(n): return isinstance(n,str) and 0<len(n)<=300 and not any(ord(c)<32 for c in n)
def get(url,limit=80*1024*1024):
    req=urllib.request.Request(url,headers={'User-Agent':'RetroVault public catalogue builder'})
    with urllib.request.urlopen(req,timeout=45) as r:
        b=r.read(limit+1)
    if len(b)>limit: raise ValueError('source trop grande')
    return b.decode('utf-8-sig',errors='replace')
def parse_dat(text):
    if text.lstrip().startswith(('<datafile','<?xml')):
        return {x.get('name') for x in ET.fromstring(text).iter() if x.tag in ('game','machine') and valid(x.get('name'))}
    return {n for m in re.finditer(r'(?:^|\n)\s*(?:game|machine)\s*\(\s*name\s+"((?:[^"\\]|\\.)*)"',text) if valid(n:=re.sub(r'\\(["\\])',r'\1',m[1]))}
def download(path):
    try:
        names=parse_dat(get(BASE+urllib.parse.quote(path,safe='/')))
        if not names: raise ValueError('catalogue vide')
        return path,names,None
    except Exception as e: return path,set(),str(e)
def extract_array(html,marker):
    start=html.index(marker)+len(marker)
    return json.JSONDecoder().raw_decode(html[start:])[0]
def base_title(s):
    # Remove known edition qualifiers only, never arbitrary subtitles.
    while True:
        new=re.sub(r'\s*\((?:USA|Europe|Japan|World|Asia|France|Germany|Spain|Italy|Australia|Brazil|Canada|Korea|China|Taiwan|Hong Kong|United Kingdom|En|Fr|De|Es|It|Ja|Rev [^)]*|v[0-9][^)]*|Beta[^)]*|Proto[^)]*|Demo[^)]*|Virtual Console|Switch Online)(?:\s*,\s*[^)]*)?\)\s*$','',s,flags=re.I)
        if new==s: break
        s=new
    m=re.match(r'^(.*), (The|A|An)$',s,re.I)
    return norm((m[2]+' '+m[1]) if m else s)
def merge_launchbox(path,merged,platforms):
    # LaunchBox entries identify games, not precise physical editions. Do not fabricate editions.
    platformmap={}
    for p in platforms:
        if p.get('system'):
            for a in (p['system'],p['name'],p.get('brand','')+' '+p['name']): platformmap[norm(a)]=p['system']
    for a,b in {'Nintendo Entertainment System':'Nintendo - Nintendo Entertainment System','Super Nintendo Entertainment System':'Nintendo - Super Nintendo Entertainment System','Nintendo Game Boy Advance':'Nintendo - Game Boy Advance','Nintendo 64':'Nintendo - Nintendo 64','Nintendo Game Boy':'Nintendo - Game Boy','Nintendo Game Boy Color':'Nintendo - Game Boy Color','Nintendo GameCube':'Nintendo - GameCube','Nintendo Wii':'Nintendo - Wii','Sega Genesis':'Sega - Mega Drive - Genesis','Sony PlayStation':'Sony - PlayStation','Sony PlayStation 2':'Sony - PlayStation 2'}.items(): platformmap[norm(a)]=b
    known={k:{base_title(n) for n in names} for k,names in merged.items()}
    result={'matched_titles':0,'added_titles':0,'unmatched_platform':0,'duplicate_rows':0}
    z=None
    if path.suffix.lower()=='.zip':
        z=zipfile.ZipFile(path)
        candidates=[i for i in z.infolist() if Path(i.filename).name.lower()=='metadata.xml' and i.file_size<=3*1024**3]
        if len(candidates)!=1: raise ValueError('Metadata.xml unique et de taille acceptable requis')
        stream=z.open(candidates[0])
    else: stream=path.open('rb')
    seen=set()
    try:
        stack=[]
        for event,el in ET.iterparse(stream,events=('start','end')):
            if event=='start': stack.append(el); continue
            tag=el.tag.rsplit('}',1)[-1]
            if tag=='Game':
                child={c.tag.rsplit('}',1)[-1]:(c.text or '').strip() for c in el}
                title=child.get('Name') or child.get('Title'); sys=platformmap.get(norm(child.get('Platform','')))
                if valid(title) and sys:
                    key=(sys,base_title(title))
                    if key in seen: result['duplicate_rows']+=1
                    else:
                        seen.add(key)
                        if key[1] in known.setdefault(sys,set()): result['matched_titles']+=1
                        else:
                            merged[sys].add(title); known[sys].add(key[1]); result['added_titles']+=1
                elif valid(title): result['unmatched_platform']+=1
            # Retain children only while parsing a Game. Remove finished top-level records.
            if len(stack)==2 or tag=='Game':
                el.clear()
                if len(stack)>1: stack[-2].remove(el)
            stack.pop()
    finally:
        stream.close()
        if z: z.close()
    return result

def build_media(out,manifest):
    """Explicit key-to-photo associations. Reject files outside approved-assets directory."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS=40_000_000
    rows=read_json(manifest) if manifest.exists() else []
    assets=(manifest.parent/'approved-assets').resolve()
    images={}; unique={}; duplicates=0
    for row in rows:
        if row.get('redistribution_authorized') is not True: raise ValueError('image sans autorisation explicite')
        file=(assets/row['file']).resolve()
        if not file.is_relative_to(assets) or not file.is_file(): raise ValueError('image hors dossier autorisé')
        if file.stat().st_size>30*1024**2: raise ValueError('image trop grande')
        key=row['key']; kind=row.get('kind','cover')
        if not isinstance(key,list) or len(key)!=2 or not all(valid(x) for x in key): raise ValueError('clé image invalide')
        if not row.get('credit'): raise ValueError('source et crédit requis')
        with Image.open(file) as raw:
            im=ImageOps.exif_transpose(raw).convert('RGBA')
            if im.width*im.height>40_000_000: raise ValueError('image trop grande')
            if kind!='pcb': im.thumbnail((480,480),Image.Resampling.LANCZOS)
            from io import BytesIO
            buf=BytesIO()
            if kind=='pcb': im.save(buf,format='WEBP',lossless=True,method=6); ext='webp'
            else: im.save(buf,format='AVIF',quality=55,speed=6); ext='avif'
            blob=buf.getvalue()
        digest=hashlib.sha256(blob).hexdigest(); rel=f'media/{digest}.{ext}'
        if digest in unique: duplicates+=1
        else: (out/rel).write_bytes(blob);unique[digest]=len(blob)
        images[json.dumps(key,ensure_ascii=False,separators=(',',':'))]={'path':rel,'credit':str(row['credit'])[:700]}
    return images,{'image_references':len(images),'unique_images':len(unique),'deduplicated_images':duplicates,'image_bytes':sum(unique.values())}

def fetch_public_hardware(out, platforms, images):
    """Publish only explicitly identified Commons photos marked public domain or CC0.
    Reuse converted content across builds. No guessing artwork, no external browser requests."""
    from PIL import Image, ImageOps
    from io import BytesIO
    import html as htmlmod
    import time
    cache=ROOT/'.rv-image-cache'
    cache.mkdir(exist_ok=True)
    api='https://commons.wikimedia.org/w/api.php'
    ua='RetroVault catalogue image builder (https://github.com/polamuss/retrovault)'
    stats={'commons_candidates':0,'commons_published':0,'commons_skipped':0,'commons_errors':0,'commons_cache_hits':0}
    files={}
    for p in platforms:
        photo=p.get('photo')
        name=p.get('name')
        if not valid(photo) or not valid(name): continue
        if not re.search(r'\.(?:png|jpe?g|webp)
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'dist');p.add_argument('--fetch',action='store_true');p.add_argument('--launchbox',type=Path);p.add_argument('--media-manifest',type=Path,default=ROOT/'tools'/'approved-images.json');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);(out/'media').mkdir(exist_ok=True)
    html=(ROOT/'index.html').read_text(encoding='utf-8'); platforms=extract_array(html,'const explorePlatforms='); offline=extract_array(html,'const offlineCatalog=')
    merged=defaultdict(set); count=0
    for p in platforms:
        if p.get('system'):
            for n in p.get('seeds',[]):
                if valid(n): merged[p['system']].add(n);count+=1
    for sys,names in offline.items():
        for n in names:
            if valid(n): merged[sys].add(n);count+=1
    failed=[]; succeeded=0
    if args.fetch:
        paths=read_json(ROOT/'tools/catalog_paths.json')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for path,names,error in pool.map(download,paths):
                if error: failed.append({'path':path,'error':error});continue
                succeeded+=1; merged[Path(path).stem].update(names);count+=len(names)
        if not succeeded: raise RuntimeError('Aucun catalogue distant accessible. Déploiement interrompu.')
    lb=merge_launchbox(args.launchbox,merged,platforms) if args.launchbox else None
    index={}
    for sys,names in sorted(merged.items()):
        if not names: continue
        filename=hashlib.sha256(sys.encode()).hexdigest()[:16]+'.json'; rel='data/catalog/'+filename
        write_json(out/rel,sorted(names,key=lambda x:(x.casefold(),x)));index[sys]=rel
    images,media_report=build_media(out,args.media_manifest)
    if args.fetch:
        media_report.update(fetch_public_hardware(out,platforms,images))
        paths={v['path'] for v in images.values()}
        media_report.update(image_references=len(images),unique_images=len(paths),deduplicated_images=len(images)-len(paths),image_bytes=sum((out/p).stat().st_size for p in paths))
    total=sum(len(a) for a in merged.values())
    report={'status':'fetched' if args.fetch else 'starter','platforms':len(index),'editions':total,'duplicate_entries_removed':max(0,count+(lb or {}).get('added_titles',0)-total),'sources_success':succeeded,'sources_failed':failed,'launchbox':lb,**media_report}
    write_json(out/'data/index.json',{'version':1,'platforms':index,'images':images,'report':report})
    write_json(out/'data/report.json',report)
    if out!=ROOT: shutil.copy2(ROOT/'index.html',out/'index.html')
    (out/'.nojekyll').touch()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    size=sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    if size>950_000_000: raise RuntimeError('Site supérieur à 950 Mo. Réduire les images ou choisir un hébergement adapté.')
if __name__=='__main__': main()
,photo,re.I): continue
        key=json.dumps(['hardware',name],ensure_ascii=False,separators=(',',':'))
        if key not in images: files.setdefault(photo,[]).append(key)
    stats['commons_candidates']=sum(map(len,files.values()))
    def request(url,limit):
        req=urllib.request.Request(url,headers={'User-Agent':ua,'Accept':'*/*'})
        with urllib.request.urlopen(req,timeout=30) as r:
            if urllib.parse.urlparse(r.geturl()).hostname not in ('commons.wikimedia.org','upload.wikimedia.org'):
                raise ValueError('hote non autorise')
            data=r.read(limit+1)
        if len(data)>limit: raise ValueError('fichier trop volumineux')
        return data
    def cached(photo):
        token=hashlib.sha256(photo.encode()).hexdigest()
        meta=cache/(token+'.json')
        if not meta.is_file(): return None
        try:
            m=read_json(meta)
            if m.get('file')!=photo or m.get('license') not in ('public domain','cc0','cc0 1.0','cc0 1.0 universal'): return None
            blob=(cache/(token+'.avif')).read_bytes()
            if hashlib.sha256(blob).hexdigest()!=m.get('digest'): return None
            return m,blob
        except (OSError,ValueError,KeyError): return None
    def publish(photo,m,blob):
        rel='media/'+m['digest']+'.avif'
        dest=out/rel
        if not dest.is_file(): dest.write_bytes(blob)
        for key in files[photo]:
            images[key]={'path':rel,'credit':m['credit'],'source':m['source'],'license':m['license']}
        stats['commons_published']+=len(files[photo])
    pending=[]
    for photo in files:
        hit=cached(photo)
        if hit:
            publish(photo,*hit)
            stats['commons_cache_hits']+=1
        else: pending.append(photo)
    for offset in range(0,len(pending),15):
        group=pending[offset:offset+15]
        params={'action':'query','format':'json','formatversion':'2','redirects':'1','prop':'imageinfo','iiprop':'url|size|mime|extmetadata','iiextmetadatafilter':'LicenseShortName|Artist|Copyrighted','titles':'|'.join('File:'+p for p in group),'maxlag':'5'}
        try:
            payload=json.loads(request(api+'?'+urllib.parse.urlencode(params),4*1024*1024))
            if 'error' in payload: raise ValueError(str(payload['error']))
            query=payload.get('query',{})
            aliases={x['from']:x['to'] for k in ('normalized','redirects') for x in query.get(k,[])}
            pages={p['title']:p for p in query.get('pages',[])}
        except Exception as e:
            stats['commons_errors']+=len(group)
            print('Commons API:',str(e))
            if isinstance(e,urllib.error.HTTPError) and e.code in (429,503): break
            continue
        for photo in group:
            try:
                title='File:'+photo
                for _ in range(5):
                    if title not in aliases: break
                    title=aliases[title]
                info=pages.get(title,{}).get('imageinfo',[])
                if not info:
                    stats['commons_skipped']+=1
                    continue
                info=info[0]
                meta=info.get('extmetadata',{})
                license=meta.get('LicenseShortName',{}).get('value','').strip().lower()
                if license not in ('public domain','cc0','cc0 1.0','cc0 1.0 universal'):
                    stats['commons_skipped']+=1
                    continue
                if meta.get('Copyrighted',{}).get('value','').lower()=='true':
                    stats['commons_skipped']+=1
                    continue
                url=info.get('url','')
                source=info.get('descriptionurl','')
                if urllib.parse.urlparse(url).hostname!='upload.wikimedia.org' or urllib.parse.urlparse(source).hostname!='commons.wikimedia.org':
                    raise ValueError('source non valide')
                if info.get('mime') not in ('image/png','image/jpeg','image/webp') or info.get('size',0)>30*1024*1024:
                    stats['commons_skipped']+=1
                    continue
                if info.get('width',0)*info.get('height',0)>40_000_000:
                    stats['commons_skipped']+=1
                    continue
                data=request(url,30*1024*1024)
                with Image.open(BytesIO(data)) as raw:
                    im=ImageOps.exif_transpose(raw).convert('RGBA')
                    im.thumbnail((480,480),Image.Resampling.LANCZOS)
                    buf=BytesIO()
                    im.save(buf,format='AVIF',quality=55,speed=6)
                blob=buf.getvalue()
                author=htmlmod.unescape(re.sub(r'<[^>]+>','',meta.get('Artist',{}).get('value',''))).strip()
                m={'file':photo,'license':license,'source':source,'credit':('Wikimedia Commons - '+author+' - '+license+' - '+source)[:700],'digest':hashlib.sha256(blob).hexdigest()}
                token=hashlib.sha256(photo.encode()).hexdigest()
                (cache/(token+'.avif')).write_bytes(blob)
                write_json(cache/(token+'.json'),m)
                publish(photo,m,blob)
                time.sleep(0.5)
            except Exception as e:
                stats['commons_errors']+=1
                print('Commons image:',photo,str(e))
                if isinstance(e,urllib.error.HTTPError) and e.code in (429,503): return stats
        time.sleep(1)
    return stats

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'dist');p.add_argument('--fetch',action='store_true');p.add_argument('--launchbox',type=Path);p.add_argument('--media-manifest',type=Path,default=ROOT/'tools'/'approved-images.json');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);(out/'media').mkdir(exist_ok=True)
    html=(ROOT/'index.html').read_text(encoding='utf-8'); platforms=extract_array(html,'const explorePlatforms='); offline=extract_array(html,'const offlineCatalog=')
    merged=defaultdict(set); count=0
    for p in platforms:
        if p.get('system'):
            for n in p.get('seeds',[]):
                if valid(n): merged[p['system']].add(n);count+=1
    for sys,names in offline.items():
        for n in names:
            if valid(n): merged[sys].add(n);count+=1
    failed=[]; succeeded=0
    if args.fetch:
        paths=read_json(ROOT/'tools/catalog_paths.json')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            for path,names,error in pool.map(download,paths):
                if error: failed.append({'path':path,'error':error});continue
                succeeded+=1; merged[Path(path).stem].update(names);count+=len(names)
        if not succeeded: raise RuntimeError('Aucun catalogue distant accessible. Déploiement interrompu.')
    lb=merge_launchbox(args.launchbox,merged,platforms) if args.launchbox else None
    index={}
    for sys,names in sorted(merged.items()):
        if not names: continue
        filename=hashlib.sha256(sys.encode()).hexdigest()[:16]+'.json'; rel='data/catalog/'+filename
        write_json(out/rel,sorted(names,key=lambda x:(x.casefold(),x)));index[sys]=rel
    images,media_report=build_media(out,args.media_manifest)
    total=sum(len(a) for a in merged.values())
    report={'status':'fetched' if args.fetch else 'starter','platforms':len(index),'editions':total,'duplicate_entries_removed':max(0,count+(lb or {}).get('added_titles',0)-total),'sources_success':succeeded,'sources_failed':failed,'launchbox':lb,**media_report}
    write_json(out/'data/index.json',{'version':1,'platforms':index,'images':images,'report':report})
    write_json(out/'data/report.json',report)
    if out!=ROOT: shutil.copy2(ROOT/'index.html',out/'index.html')
    (out/'.nojekyll').touch()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    size=sum(f.stat().st_size for f in out.rglob('*') if f.is_file())
    if size>950_000_000: raise RuntimeError('Site supérieur à 950 Mo. Réduire les images ou choisir un hébergement adapté.')
if __name__=='__main__': main()

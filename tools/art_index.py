"""Build small indexes of publicly referenced game images, not copies of artwork."""
import concurrent.futures
import configparser
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

UA='RetroVault index builder (https://github.com/polamuss/retrovault)'
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.rv-image-cache'/'indexes-v1'
KINDS=('Named_Boxarts','Named_Titles','Named_Snaps')

def request_json(url, limit=32*1024*1024):
    headers={'User-Agent':UA,'Accept':'application/json'}
    if urllib.parse.urlparse(url).hostname=='api.github.com' and os.getenv('GITHUB_TOKEN'):
        headers['Authorization']='Bearer '+os.environ['GITHUB_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=40) as r:
        data=r.read(limit+1)
    if len(data)>limit: raise ValueError('index trop volumineux')
    return json.loads(data)

def module_map():
    url='https://raw.githubusercontent.com/libretro-thumbnails/libretro-thumbnails/master/.gitmodules'
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':UA}),timeout=30) as r:
        raw=r.read(1024*1024).decode('utf-8')
    cfg=configparser.ConfigParser(interpolation=None)
    cfg.read_string(raw)
    result={}
    for section in cfg.sections():
        path=cfg[section].get('path','')
        repo=cfg[section].get('url','')
        match=re.fullmatch(r'https://github\.com/libretro-thumbnails/([A-Za-z0-9_.-]+?)(?:\.git)?',repo)
        branch=cfg[section].get('branch','master')
        if path and match and re.fullmatch(r'[A-Za-z0-9_.-]+',branch):
            result[path]=(match[1],branch)
    return result

def files_for(repo,branch):
    CACHE.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256((repo+'@'+branch).encode()).hexdigest()
    file=CACHE/(key+'.json')
    old=None
    try:
        old=json.loads(file.read_text(encoding='utf-8'))
        if time.time()-file.stat().st_mtime<7*86400: return old
    except (OSError,ValueError): pass
    try:
        base='https://api.github.com/repos/libretro-thumbnails/'+repo+'/git/trees/'
        result={k:[] for k in KINDS}
        def add(kind,filename,row):
            if row.get('type')=='blob' and kind in result and '/' not in filename and filename.lower().endswith('.png') and len(filename)<=350:
                result[kind].append(filename[:-4])
        try:
            data=request_json(base+branch+'?recursive=1')
        except Exception:
            data={'truncated':True}
        if data.get('truncated'):
            # Three independent directory trees are smaller and avoid recursive-tree API truncation.
            root=request_json(base+branch)
            for row in root.get('tree',[]):
                kind=row.get('path','')
                sha=row.get('sha','')
                if kind not in result or not re.fullmatch(r'[a-f0-9]{40}',sha): continue
                sub=request_json(base+sha)
                if sub.get('truncated'): raise ValueError('dossier images incomplet '+kind)
                for file in sub.get('tree',[]): add(kind,file.get('path',''),file)
        else:
            for row in data.get('tree',[]):
                kind,sep,filename=row.get('path','').partition('/')
                add(kind,filename,row)
        file.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return result
    except Exception as e:
        if old is not None: return old
        print('Index Libretro indisponible:',repo,str(e))
        return None

def index_games(out,merged,base_title,write_json):
    result={}
    stats={'art_platforms':0,'art_matches':0,'art_exact':0,'art_variant':0,'art_screenshots':0,'art_errors':0}
    try: sources=module_map()
    except Exception as e:
        print('Liste des index Libretro indisponible:',str(e))
        return result,stats
    aliases={'Microsoft - XBOX':'Microsoft - Xbox','Microsoft - XBOX 360':'Microsoft - Xbox 360','NEC - PC Engine - TurboGrafx 16':'NEC - PC Engine - TurboGrafx 16'}
    def build(system):
        source_system=system if system in sources else aliases.get(system,system)
        if source_system not in sources:
            match=[s for s in sources if s.casefold()==system.casefold()]
            if len(match)!=1: return system,None
            source_system=match[0]
        repo,branch=sources[source_system]
        names=files_for(repo,branch)
        if names is None: return system,False
        exact={}
        groups=defaultdict(list)
        for priority,kind in enumerate(KINDS):
            for name in names[kind]:
                exact.setdefault(name.casefold(),(priority,name))
                base=base_title(name)
                if base: groups[base].append((priority,name))
        matches={}
        counts=[0,0,0]
        for title in sorted(merged[system]):
            clean=re.sub(r'[&*/:<>?\\|"]','_',title)
            hit=exact.get(clean.casefold())
            alternate=False
            if hit is None:
                pool=groups.get(base_title(clean),[])
                if not pool: continue
                # Same normalized title, not an unrelated search result.
                hit=min(pool,key=lambda r:(r[0],r[1].casefold()))
                alternate=True
            priority,filename=hit
            matches[title]=[priority,filename,int(alternate)]
            counts[int(alternate)]+=1
            if priority!=0: counts[2]+=1
        digest=hashlib.sha256(system.encode()).hexdigest()[:16]
        path='data/art/'+digest+'.json'
        write_json(out/path,{'repo':repo,'branch':branch,'rows':matches})
        return system,(path,counts)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for system,row in pool.map(build,sorted(merged)):
            if row is False: stats['art_errors']+=1
            elif row:
                path,counts=row
                result[system]=path
                stats['art_platforms']+=1
                stats['art_exact']+=counts[0]
                stats['art_variant']+=counts[1]
                stats['art_screenshots']+=counts[2]
    stats['art_matches']=stats['art_exact']+stats['art_variant']
    return result,stats

def discover_hardware(platforms,mapping):
    """Exact curated encyclopedia articles, followed by Commons license validation in build.py."""
    selected={p['name']:p for p in platforms if not p.get('photo') and p.get('name') in mapping}
    cache=CACHE/'hardware.json'
    try: known=json.loads(cache.read_text(encoding='utf-8'))
    except (OSError,ValueError): known={}
    titles={mapping[name] for name in selected}
    pending=sorted(titles-set(known))
    for start in range(0,len(pending),15):
        batch=pending[start:start+15]
        query={'action':'query','format':'json','formatversion':'2','redirects':'1','prop':'pageimages|pageprops','piprop':'name','pilicense':'free','titles':'|'.join(batch),'maxlag':'5'}
        try:
            result=request_json('https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode(query),4*1024*1024)
            if 'error' in result: raise ValueError(str(result['error']))
            q=result.get('query',{})
            aliases={r['from']:r['to'] for k in ('normalized','redirects') for r in q.get(k,[])}
            pages={r['title']:r for r in q.get('pages',[])}
            for title in batch:
                resolved=title
                for _ in range(5):
                    if resolved not in aliases: break
                    resolved=aliases[resolved]
                row=pages.get(resolved,{})
                # Avoid redirects to unrelated subjects and generic illustrations.
                photo=row.get('pageimage')
                if 'disambiguation' in row.get('pageprops',{}) or not isinstance(photo,str) or re.search(r'logo|icon|flag|screenshot',photo,re.I): continue
                if Path(photo).suffix.lower() not in ('.jpg','.jpeg','.png','.webp'): continue
                known[title]=photo
            time.sleep(1)
        except Exception as e:
            print('Recherche de materiel:',str(e))
            break
    CACHE.mkdir(parents=True,exist_ok=True)
    cache.write_text(json.dumps(known,ensure_ascii=False),encoding='utf-8')
    result=[]
    for name,p in selected.items():
        if mapping[name] in known: result.append((name,known[mapping[name]]))
    return result


def search_missing_hardware(platforms, images, free_license, config):
    """One targeted Commons search per missing hardware model, with cached candidates."""
    import html as htmlmod
    import unicodedata
    aliases=config.get('aliases',{})
    cached_file=CACHE/'commons-search-v2.json'
    try: cached=json.loads(cached_file.read_text(encoding='utf-8'))
    except (OSError,ValueError): cached={}
    now=time.time()
    def norm(s):
        s=unicodedata.normalize('NFKD',str(s or '').casefold())
        s=''.join(c for c in s if not unicodedata.combining(c))
        return ' '.join(re.sub(r'[^a-z0-9]+',' ',s).split())
    def contains(text,token): return bool(token) and (' '+token+' ') in (' '+text+' ')
    def names(p):
        name=p['name']
        a=aliases.get(name,[name])
        if not p.get('parent'):
            a=a+[re.sub(r'\s+originale?$', '',name,flags=re.I)]
        model=p.get('model','')
        if re.fullmatch(r'[A-Z]{2,5}[- ]?[0-9]{2,5}[A-Z]?',model,re.I):
            a=a+[model]
        return list(dict.fromkeys(norm(n) for n in a if len(norm(n))>=3))
    byname={p['name']:p for p in platforms}
    byparent=defaultdict(list)
    for p in platforms:
        if p.get('parent'): byparent[p['parent']].append(p)
    banned=re.compile(r'\b(logo|icon|flag|diagram|schematic|manual|motherboard|pcb|teardown|disassembly|prototype drawing|advertisement|poster|box art|fan art|cosplay|protein|gene|film|album|screenshot|gameplay|packaging)\b')
    accessory=re.compile(r'\b(controller|joystick|gamepad|accessory|peripheral|adapter|manette|memory card|add on|expansion|sensor|camera|dock|printer|robot|microphone|keyboard|mouse|cable|wheel|bongos|maracas|headset|charger|trackball|volant|carte memoire|gun|zapper|remote|multitap)\b')
    hardware=re.compile(r'\b(console|consoles|computer|computers|ordinateur|handheld|microcomputer|video game|gaming system|game system|home computer|personal computer|controller|accessory|system|set)\b')
    def rank(row,p):
        info=row.get('imageinfo',[{}])[0]
        meta=info.get('extmetadata',{})
        license=meta.get('LicenseShortName',{}).get('value','').strip().lower()
        if not free_license(license): return None
        file=row.get('title','').removeprefix('File:')
        if Path(file).suffix.lower() not in ('.png','.jpg','.jpeg','.webp'): return None
        if info.get('mime') not in ('image/png','image/jpeg','image/webp'): return None
        if not 0<info.get('width',0)*info.get('height',0)<=40000000 or info.get('size',0)>30*1024*1024: return None
        t=norm(Path(file).stem)
        raw=' '.join([meta.get('ImageDescription',{}).get('value',''),meta.get('Categories',{}).get('value','')])
        desc=norm(htmlmod.unescape(re.sub(r'<[^>]+>',' ',raw)))
        alltext=t+' '+desc
        if banned.search(t): return None
        a=names(p)
        hits=[n for n in a if contains(t,n)]
        if not hits: return None
        brand=norm(p.get('brand','').split(' / ')[0])
        is_acc=p.get('category')=='accessoire'
        if is_acc and not accessory.search(alltext): return None
        if not is_acc and not (hardware.search(alltext) or contains(alltext,brand) and len(max(hits,key=len))>=5): return None
        if not is_acc and accessory.search(t) and not re.search(r'\b(console|computer|handheld|set|system)\b',t): return None
        if p['name']=='MSX' and re.search(r'\bmsx\s*2\b',alltext): return None
        if p['name']=='MSX2' and re.search(r'msx\s*2\s*(plus|\+)',file+' '+raw,re.I): return None
        if p.get('parent'):
            parent=byname.get(p['parent'],{})
            parent_alias=names(parent) if parent else []
            if not any(n not in parent_alias for n in hits): return None
        family=p.get('parent') or p['name']
        for other in byparent.get(family,[]):
            if other['name']==p['name']: continue
            if any(len(n)>=5 and n not in a and not any(contains(x,n) for x in a) and contains(t,n) for n in names(other)):
                return None
        score=max(len(n) for n in hits)*3+10*contains(t,brand)
        if hardware.search(t): score+=8
        if re.search(r'\b(front|console|set|handheld|controller|computer|open)\b',t): score+=5
        if re.search(r'\b(back|rear|bottom|side|detail|closeup|comparison|collection|museum)\b',t): score-=5
        return (score,file)
    selected=[p for p in platforms if p.get('category')!='logiciel' and json.dumps(['hardware',p['name']],ensure_ascii=False,separators=(',',':')) not in images]
    selected.sort(key=lambda p:(p.get('category')=='accessoire',bool(p.get('parent')),p['name']))
    results=[]
    stats={'commons_search_targets':len(selected),'commons_search_requests':0,'commons_search_cache_hits':0,'commons_search_candidates':0}
    for p in selected:
        key=p['name']
        previous=cached.get(key,{})
        if previous.get('files') or now-previous.get('at',0)<7*86400:
            stats['commons_search_cache_hits']+=1
            found=previous.get('files',[])
        else:
            a=names(p)
            if not a: continue
            # Search the longest precise alias, preferring the original name when comparable.
            query=max(a,key=len)
            brand=p.get('brand','').split(' / ')[0]
            if brand and not contains(query,norm(brand)): query=brand+' '+query
            if p.get('category')=='accessoire': query+=' video game accessory'
            else: query+=' console'
            params={'action':'query','format':'json','formatversion':'2','generator':'search','gsrsearch':query,'gsrnamespace':'6','gsrlimit':'18','prop':'imageinfo','iiprop':'size|mime|extmetadata','iiextmetadatafilter':'LicenseShortName|ImageDescription|Categories','maxlag':'5'}
            try:
                payload=request_json('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(params),4*1024*1024)
                if 'error' in payload: raise ValueError(str(payload['error']))
                ranked=[r for row in payload.get('query',{}).get('pages',[]) if (r:=rank(row,p))]
                found=[file for score,file in sorted(ranked,reverse=True)[:3]]
                cached[key]={'at':now,'files':found}
                stats['commons_search_requests']+=1
                time.sleep(1.2)
            except Exception as e:
                print('Commons search:',key,str(e))
                if getattr(e,'code',None) in (429,503) or 'maxlag' in str(e).lower(): break
                time.sleep(2)
                continue
        for file in found:
            results.append((key,file))
            stats['commons_search_candidates']+=1
    CACHE.mkdir(parents=True,exist_ok=True)
    cached_file.write_text(json.dumps(cached,ensure_ascii=False),encoding='utf-8')
    return results,stats

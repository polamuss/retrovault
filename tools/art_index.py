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
        data=request_json('https://api.github.com/repos/libretro-thumbnails/'+repo+'/git/trees/'+branch+'?recursive=1')
        if data.get('truncated'): raise ValueError('arbre incomplet')
        result={k:[] for k in KINDS}
        for row in data.get('tree',[]):
            path=row.get('path','')
            kind,sep,filename=path.partition('/')
            if row.get('type')=='blob' and kind in result and '/' not in filename and filename.lower().endswith('.png') and len(filename)<=350:
                result[kind].append(filename[:-4])
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

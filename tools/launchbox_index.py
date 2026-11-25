"""Use supplied LaunchBox metadata, never publish the full XML or its descriptions."""
import collections, gzip, hashlib, json, re, time, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='a224502ef1be29494cb7c3705788c4731a9558a74dec8fdc81096a95c60dc8a5'
URL='https://gamesdb.launchbox-app.com/Metadata.zip'
TYPES={'Box - Front':0,'Box - Front - Reconstructed':1,'Cart - Front':2,'Advertisement Flyer - Front':3,'Screenshot - Game Title':4,'Screenshot - Gameplay':5}
FILE=re.compile(r'(?:r2_)?[a-z0-9_-]{10,120}\.(?:png|jpe?g|webp)',re.I)
ALIASES={'3DO Interactive Multiplayer':'The 3DO Company - 3DO','Nintendo Game & Watch':'Handheld Electronic Game','Nintendo Famicom Disk System':'Nintendo - Family Computer Disk System','Sega Genesis':'Sega - Mega Drive - Genesis','Sega Master System':'Sega - Master System - Mark III','Sega CD':'Sega - Mega-CD - Sega CD','Sony PSP':'Sony - PlayStation Portable','Sony Playstation Vita':'Sony - PlayStation Portable Vita','Microsoft Xbox Series X/S':'Microsoft - Xbox Series','Atari 800':'Atari - 8-bit Family','SNK Neo Geo AES':'SNK - Neo Geo','NEC TurboGrafx-16':'NEC - PC Engine - TurboGrafx 16','NEC TurboGrafx-CD':'NEC - PC Engine CD - TurboGrafx-CD','PC Engine SuperGrafx':'NEC - PC Engine SuperGrafx','Mattel Intellivision':'Mattel - Intellivision','Magnavox Odyssey 2':'Magnavox - Odyssey2','Commodore Amiga CD32':'Commodore - CD32','BBC Microcomputer System':'Acorn - BBC Micro','Fujitsu FM Towns Marty':'Fujitsu - FM Towns','NEC PC-9801':'NEC - PC-98','Sinclair ZX-81':'Sinclair - ZX 81','Texas Instruments TI 99/4A':'Texas Instruments - TI-99_4A','WonderSwan':'Bandai - WonderSwan','WonderSwan Color':'Bandai - WonderSwan Color','Arcade':'MAME','Nintendo 64DD':'Nintendo - Nintendo 64DD'}

def extract(src):
    games={}; aliases=collections.defaultdict(set); media={}; counts=collections.Counter(); stack=[]
    with zipfile.ZipFile(src) as z:
        info=z.getinfo('Metadata.xml')
        if info.file_size>2*1024**3: raise ValueError('Metadata.xml trop volumineux')
        with z.open(info) as stream:
            for ev,e in ET.iterparse(stream,events=('start','end')):
                if ev=='start': stack.append(e); continue
                if len(stack)==2:
                    counts[e.tag]+=1
                    id=e.findtext('DatabaseID') or ''
                    if e.tag=='Game' and id.isdigit():
                        n,p=e.findtext('Name'),e.findtext('Platform')
                        if n and p and len(n)<=300 and len(p)<=150: games[id]=(p,n)
                    elif e.tag=='GameAlternateName' and id.isdigit():
                        n=e.findtext('AlternateName')
                        if n and len(n)<=300 and len(aliases[id])<16: aliases[id].add(n)
                    elif e.tag=='GameImage' and id.isdigit():
                        f=e.findtext('FileName') or ''; kind=TYPES.get(e.findtext('Type')); reg=(e.findtext('Region') or '')[:80]
                        if kind is not None and FILE.fullmatch(f):
                            a=media.setdefault(id,{})
                            key=(kind,reg)
                            if key not in a or f<a[key]: a[key]=f
                    stack[-2].remove(e)
                stack.pop()
    result=collections.defaultdict(list)
    for id,(p,n) in games.items():
        a=media.get(id,{})
        rows=sorted([[f,k,r] for (k,r),f in a.items()],key=lambda x:(x[1],0 if x[2] in ('Europe','North America','World','') else 1,x[2],x[0]))
        result[p].append([n,sorted(aliases.get(id,())),[x for x in rows if x[1]<4][:3]+[x for x in rows if x[1]>=4][:1]])
    return {'schema':1,'archive_sha256':hashlib.file_digest(open(src,'rb'),'sha256').hexdigest(),'source_counts':dict(counts),'platforms':dict(result)}

def load_index():
    supplied=ROOT/'tools'/'launchbox-index.json.gz'
    cache=ROOT/'.rv-image-cache'/'launchbox-index-v1.json.gz'
    if supplied.is_file():
        with gzip.open(supplied,'rt',encoding='utf-8') as f: return json.load(f),'uploaded-index'
    if cache.is_file():
        with gzip.open(cache,'rt',encoding='utf-8') as f: data=json.load(f)
        if data.get('archive_sha256')==EXPECTED or time.time()-cache.stat().st_mtime<7*86400: return data,'cached-source'
    else: data=None
    archive=cache.with_suffix('.zip')
    archive.parent.mkdir(parents=True,exist_ok=True)
    try:
        request=urllib.request.Request(URL,headers={'User-Agent':'RetroVault metadata index (https://github.com/polamuss/retrovault)'})
        with urllib.request.urlopen(request,timeout=90) as r,archive.open('wb') as f:
            size=0
            while chunk:=r.read(1024*1024):
                size+=len(chunk)
                if size>250*1024**2: raise ValueError('archive trop volumineuse')
                f.write(chunk)
        result=extract(archive)
        with gzip.open(cache,'wt',encoding='utf-8',compresslevel=6) as f: json.dump(result,f,ensure_ascii=False,separators=(',',':'))
        return result,'official-source'
    except Exception as exc:
        if data: return data,'cached-source'
        raise RuntimeError('LaunchBox indisponible: '+str(exc))
    finally:
        archive.unlink(missing_ok=True)

def apply_index(out,merged,platforms,base_title,norm,write_json):
    report={'launchbox_source':None,'launchbox_archive_matches_upload':False,'launchbox_matches':0,'launchbox_added_titles':0,'launchbox_image_references':0,'launchbox_platforms':0,'launchbox_unmapped_platforms':0,'launchbox_source_games':0}
    try: data,source=load_index()
    except Exception as e:
        report['launchbox_error']=str(e); print(report['launchbox_error']); return {},report
    report.update(launchbox_source=source,launchbox_archive_matches_upload=data.get('archive_sha256')==EXPECTED,launchbox_archive_sha256=data.get('archive_sha256'),launchbox_source_games=data.get('source_counts',{}).get('Game',0))
    system_names=set(merged)|{p['system'] for p in platforms if p.get('system')}
    targets=collections.defaultdict(set)
    for system in system_names: targets[norm(system)].add(system)
    for p in platforms:
        sys=p.get('system')
        if not sys or p.get('parent'): continue
        for a in [p.get('name',''),p.get('brand','')+' '+p.get('name','')]:
            if a.strip(): targets[norm(a)].add(sys)
    per=collections.defaultdict(list)
    for platform,rows in data.get('platforms',{}).items():
        sys=ALIASES.get(platform)
        if sys not in system_names:
            match=targets.get(norm(platform),set())
            sys=next(iter(match)) if len(match)==1 else None
        if not sys:
            report['launchbox_unmapped_platforms']+=1
            continue
        per[sys].extend(rows)
    output={}
    for system,rows in sorted(per.items()):
        exact=collections.defaultdict(list)
        known={base_title(n) for n in merged[system]}
        for row in rows:
            if not isinstance(row,list) or len(row)!=3: continue
            title,aliases,media=row
            if not isinstance(title,str) or not title or len(title)>300: continue
            keys={base_title(n) for n in [title,*aliases] if isinstance(n,str) and len(n)<=300}
            keys.discard('')
            if not keys: continue
            if not known.intersection(keys):
                merged[system].add(title)
                known.add(base_title(title))
                report['launchbox_added_titles']+=1
            valid=[m for m in media if isinstance(m,list) and len(m)==3 and isinstance(m[0],str) and FILE.fullmatch(m[0]) and m[1] in range(6) and isinstance(m[2],str)]
            if not valid: continue
            for k in keys: exact[k].append((title,valid))
        index={}
        for title in sorted(merged[system]):
            hits=exact.get(base_title(title),[])
            if not hits: continue
            # Ambiguous alternate-name matches are not silently merged.
            canonical=[h for h in hits if norm(h[0])==norm(title)]
            if canonical: hits=canonical
            if len({norm(h[0]) for h in hits})!=1: continue
            images=[]
            for _,media in hits:
                for img in media:
                    if img not in images: images.append(img)
            index[title]=sorted(images,key=lambda x:(x[1],x[2],x[0]))[:5]
        if not index: continue
        path='data/launchbox/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
        write_json(out/path,index)
        output[system]=path
        report['launchbox_matches']+=len(index)
        report['launchbox_image_references']+=sum(len(r) for r in index.values())
    report['launchbox_platforms']=len(output)
    return output,report

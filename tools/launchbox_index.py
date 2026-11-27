"""Use supplied LaunchBox metadata, never publish the full XML or its descriptions."""
import collections, gzip, hashlib, json, os, re, time, urllib.request, zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EXPECTED='a224502ef1be29494cb7c3705788c4731a9558a74dec8fdc81096a95c60dc8a5'
URL='https://gamesdb.launchbox-app.com/Metadata.zip'
TYPES={'Box - Front':0,'Box - Front - Reconstructed':1,'Cart - Front':2,'Advertisement Flyer - Front':3,'Screenshot - Game Title':4,'Screenshot - Gameplay':5,'Box - 3D':6,'Cart - 3D':7}
FILE=re.compile(r'(?:r2_)?[a-z0-9_-]{10,120}\.(?:png|jpe?g|webp)',re.I)
ALIASES={'3DO Interactive Multiplayer':'The 3DO Company - 3DO','Nintendo Game & Watch':'Handheld Electronic Game','Nintendo Famicom Disk System':'Nintendo - Family Computer Disk System','Sega Genesis':'Sega - Mega Drive - Genesis','Sega Master System':'Sega - Master System - Mark III','Sega CD':'Sega - Mega-CD - Sega CD','Sony PSP':'Sony - PlayStation Portable','Sony Playstation Vita':'Sony - PlayStation Portable Vita','Microsoft Xbox Series X/S':'Microsoft - Xbox Series','Atari 800':'Atari - 8-bit Family','SNK Neo Geo AES':'SNK - Neo Geo','NEC TurboGrafx-16':'NEC - PC Engine - TurboGrafx 16','NEC TurboGrafx-CD':'NEC - PC Engine CD - TurboGrafx-CD','PC Engine SuperGrafx':'NEC - PC Engine SuperGrafx','Mattel Intellivision':'Mattel - Intellivision','Magnavox Odyssey 2':'Magnavox - Odyssey2','Commodore Amiga CD32':'Commodore - CD32','BBC Microcomputer System':'Acorn - BBC Micro','Fujitsu FM Towns Marty':'Fujitsu - FM Towns','NEC PC-9801':'NEC - PC-98','Sinclair ZX-81':'Sinclair - ZX 81','Texas Instruments TI 99/4A':'Texas Instruments - TI-99_4A','WonderSwan':'Bandai - WonderSwan','WonderSwan Color':'Bandai - WonderSwan Color','Arcade':'MAME','Nintendo 64DD':'Nintendo - Nintendo 64DD','Arduboy':'Arduboy Inc - Arduboy','NEC PC-8801':'NEC - PC-88','Spectravideo':'Spectravideo - SVI-318 - SVI-328','Sony Playstation Vita':'Sony - PlayStation Vita','SNK Neo Geo MVS':'SNK - Neo Geo MVS'}

def extract(src, expanded=False):
    games={}; aliases=collections.defaultdict(set); media={}; counts=collections.Counter(); stack=[]; excluded=collections.defaultdict(list); release_types=collections.Counter()
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
                        release=(e.findtext('ReleaseType') or '').strip()
                        release_types[release]+=1
                        if n and p and len(n)<=300 and len(p)<=150:
                            if re.search(r'\brom\s*hack\b|^hack$',release,re.I): excluded[p].append(n)
                            else: games[id]=(p,n)
                    elif e.tag=='GameAlternateName' and id.isdigit():
                        n=e.findtext('AlternateName')
                        if n and len(n)<=300 and (expanded or len(aliases[id])<16): aliases[id].add(n)
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
        ranks={0:0,1:1,6:2,2:3,3:4,7:5,4:6,5:7}
        rows=sorted([[f,k,r] for (k,r),f in a.items()],key=lambda x:(ranks[x[1]],0 if x[2] in ('Europe','North America','World','') else 1,0 if x[0].lower().endswith(('.jpg','.jpeg')) else 1,x[2],x[0]))
        result[p].append([n,sorted(aliases.get(id,())),[x for x in rows if x[1] in (0,1)][:6]+[x for x in rows if x[1] in (2,3,6,7)][:3]+[x for x in rows if x[1] in (4,5)][:1]])
    return {'schema':4 if expanded else 3,'rom_hacks':dict(excluded),'release_types':dict(release_types),'archive_sha256':hashlib.file_digest(open(src,'rb'),'sha256').hexdigest(),'source_counts':dict(counts),'platforms':dict(result)}

def load_index(expanded=False):
    supplied=ROOT/'tools'/'launchbox-index.json.gz'
    schema=4 if expanded else 3
    cache=ROOT/'.rv-image-cache'/('launchbox-images-v4.json.gz' if expanded else 'launchbox-index-v3.json.gz')
    refresh=expanded and os.getenv('RV_REFRESH_SOURCES')=='1'
    if supplied.is_file():
        with gzip.open(supplied,'rt',encoding='utf-8') as f: supplied_data=json.load(f)
        if supplied_data.get('schema')==schema and not refresh: return supplied_data,'uploaded-index'
    if cache.is_file():
        with gzip.open(cache,'rt',encoding='utf-8') as f: data=json.load(f)
        if data.get('schema')!=schema: data=None
        elif not refresh and (not expanded and data.get('archive_sha256')==EXPECTED or time.time()-cache.stat().st_mtime<7*86400): return data,'cached-source'
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
        result=extract(archive,expanded=expanded)
        with gzip.open(cache,'wt',encoding='utf-8',compresslevel=6) as f: json.dump(result,f,ensure_ascii=False,separators=(',',':'))
        return result,'official-source'
    except Exception as exc:
        if data: return data,'cached-source'
        raise RuntimeError('LaunchBox indisponible: '+str(exc))
    finally:
        archive.unlink(missing_ok=True)

def apply_index(out,merged,platforms,base_title,norm,write_json,is_rom_hack,images_only=False,previous_art=None):
    report={'launchbox_source':None,'launchbox_archive_matches_upload':False,'launchbox_matches':0,'launchbox_added_titles':0,'launchbox_image_references':0,'launchbox_platforms':0,'launchbox_unmapped_platforms':0,'launchbox_source_games':0}
    try: data,source=load_index(expanded=images_only)
    except Exception as e:
        report['launchbox_error']=str(e); print(report['launchbox_error']); return {},{},report
    report.update(launchbox_source=source,launchbox_archive_matches_upload=data.get('archive_sha256')==EXPECTED,launchbox_archive_sha256=data.get('archive_sha256'),launchbox_source_games=data.get('source_counts',{}).get('Game',0))
    system_names=set(merged) if images_only else set(merged)|{p['system'] for p in platforms if p.get('system')}
    targets=collections.defaultdict(set)
    for system in system_names: targets[norm(system)].add(system)
    for p in platforms:
        sys=p.get('system')
        if not sys or p.get('parent'): continue
        for a in [p.get('name',''),p.get('brand','')+' '+p.get('name','')]:
            if a.strip(): targets[norm(a)].add(sys)
    per=collections.defaultdict(list)
    platform_to_system={}
    for platform,rows in data.get('platforms',{}).items():
        sys=ALIASES.get(platform)
        if sys not in system_names:
            match=targets.get(norm(platform),set())
            sys=next(iter(match)) if len(match)==1 else None
        if not sys:
            report['launchbox_unmapped_platforms']+=1
            continue
        per[sys].extend(rows)
        platform_to_system[platform]=sys
    blocked=collections.defaultdict(set)
    for platform,titles in data.get('rom_hacks',{}).items():
        sys=platform_to_system.get(platform)
        if sys: blocked[sys].update(base_title(n) for n in titles)
    report['launchbox_rom_hacks_excluded']=sum(len(v) for v in data.get('rom_hacks',{}).values())
    report['launchbox_hacks_removed_from_catalog']=0
    report['launchbox_aliases_grouped']=0
    output={}
    groups={}
    digital=re.compile(r' \((?:Digital|PSN|Games on Demand|Download Play)\)$',re.I)
    for sys in sorted(system_names):
        base=digital.sub('',sys)
        if base!=sys and base in per: per[sys].extend(per[base])
    for system,rows in sorted(per.items()):
        exact=collections.defaultdict(list)
        alias_owners=collections.defaultdict(set)
        canonical_keys={base_title(r[0]) for r in rows if isinstance(r,list) and len(r)==3 and isinstance(r[0],str) and not is_rom_hack(r[0])}
        rejected=blocked[system]-canonical_keys
        excluded={n for n in merged[system] if base_title(n) in rejected or is_rom_hack(n)}
        if not images_only:
            merged[system].difference_update(excluded)
            report['launchbox_hacks_removed_from_catalog']+=len(excluded)
        known={base_title(n) for n in merged[system]}
        for row in rows:
            if not isinstance(row,list) or len(row)!=3: continue
            title,aliases,media=row
            if not isinstance(title,str) or not title or len(title)>300 or is_rom_hack(title): continue
            keys={base_title(n) for n in [title,*aliases] if isinstance(n,str) and len(n)<=300}
            keys.discard('')
            if not keys: continue
            canonical=base_title(title)
            for k in keys: alias_owners[k].add(canonical)
            if not images_only and not known.intersection(keys) and not digital.search(system):
                merged[system].add(title)
                known.add(base_title(title))
                report['launchbox_added_titles']+=1
            valid=[m for m in media if isinstance(m,list) and len(m)==3 and isinstance(m[0],str) and FILE.fullmatch(m[0]) and m[1] in range(8) and isinstance(m[2],str)]
            if not valid: continue
            for k in keys: exact[k].append((title,valid))
        alias_map={}
        # Only explicitly documented names with a single canonical owner can be merged.
        for k,owners in alias_owners.items():
            if len(owners)==1 and k not in canonical_keys:
                owner=next(iter(owners))
                if owner!=k: alias_map[k]=owner
        if alias_map:
            if images_only:
                groups[system]=alias_map
            else:
                path='data/groups/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
                write_json(out/path,alias_map)
                groups[system]=path
            report['launchbox_aliases_grouped']+=len(alias_map)
        index={}
        for title in sorted(merged[system]):
            hits=exact.get(base_title(title),[])
            if images_only and not hits:
                # TOSEC / catalog filenames sometimes contain an extra publisher/year suffix.
                stripped=re.sub(r'\s*\((?:19\d{2}|20\d{2})(?:\s*[-,]\s*[^)]*)?\)(?:\s*\([^)]*\))*\s*
            if not hits: continue
            # Ambiguous alternate-name matches are not silently merged.
            canonical=[h for h in hits if base_title(h[0])==base_title(title)]
            if canonical: hits=canonical
            if len({base_title(h[0]) for h in hits})!=1: continue
            images=[]
            for _,media in hits:
                for img in media:
                    if img not in images: images.append(img)
            ranks={0:0,1:1,6:2,2:3,3:4,7:5,4:6,5:7}
            index[title]=sorted(images,key=lambda x:(ranks[x[1]],0 if x[0].lower().endswith(('.jpg','.jpeg')) else 1,x[2],x[0]))[:10]
        if images_only and system in (previous_art or {}):
            previous=json.loads((out/previous_art[system]).read_text(encoding='utf-8'))
            for title,refs in previous.items():
                index[title]=refs+[ref for ref in index.get(title,[]) if ref not in refs]
        if not index: continue
        path='data/launchbox/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
        write_json(out/path,index)
        output[system]=path
        report['launchbox_matches']+=len(index)
        report['launchbox_image_references']+=sum(len(r) for r in index.values())
    report['launchbox_platforms']=len(output)
    return output,groups,report
,'',title)
                if stripped!=title and len(base_title(stripped))>=5:
                    hits=exact.get(base_title(stripped),[])
            if not hits: continue
            # Ambiguous alternate-name matches are not silently merged.
            canonical=[h for h in hits if base_title(h[0])==base_title(title)]
            if canonical: hits=canonical
            if len({base_title(h[0]) for h in hits})!=1: continue
            images=[]
            for _,media in hits:
                for img in media:
                    if img not in images: images.append(img)
            ranks={0:0,1:1,6:2,2:3,3:4,7:5,4:6,5:7}
            index[title]=sorted(images,key=lambda x:(ranks[x[1]],0 if x[0].lower().endswith(('.jpg','.jpeg')) else 1,x[2],x[0]))[:10]
        if images_only and system in (previous_art or {}):
            previous=json.loads((out/previous_art[system]).read_text(encoding='utf-8'))
            for title,refs in previous.items():
                index[title]=refs+[ref for ref in index.get(title,[]) if ref not in refs]
        if not index: continue
        path='data/launchbox/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
        write_json(out/path,index)
        output[system]=path
        report['launchbox_matches']+=len(index)
        report['launchbox_image_references']+=sum(len(r) for r in index.values())
    report['launchbox_platforms']=len(output)
    return output,groups,report

"""Index GameTDB title/serial references, without mirroring image files."""
import hashlib, json, os, re, time, urllib.request
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.rv-image-cache'/'gametdb'
SYSTEMS={
 'Nintendo - Wii':('wii','wiitdb','png'),
 'Nintendo - GameCube':('wii','wiitdb','png'),
 'Nintendo - Wii U':('wiiu','wiiutdb','png'),
 'Nintendo - Nintendo DS':('ds','dstdb','png'),
 'Sony - PlayStation 3':('ps3','ps3tdb','jpg'),
}
def title_rows(db):
    CACHE.mkdir(parents=True,exist_ok=True)
    file=CACHE/(db+'.json')
    try: old=json.loads(file.read_text(encoding='utf-8'))
    except (OSError,ValueError): old=None
    if old and os.getenv('RV_REFRESH_SOURCES')!='1' and time.time()-file.stat().st_mtime<14*86400: return old
    try:
        req=urllib.request.Request('https://www.gametdb.com/'+db+'.txt?LANG=EN',headers={'User-Agent':'RetroVault catalogue metadata index'})
        with urllib.request.urlopen(req,timeout=35) as r: raw=r.read(8*1024*1024+1)
        if len(raw)>8*1024*1024: raise ValueError('liste trop grande')
        rows=[]
        for line in raw.decode('utf-8-sig',errors='replace').splitlines():
            m=re.fullmatch(r'([A-Z0-9]{4,10})\s*=\s*(.{1,300})',line.strip())
            if m: rows.append([m[1],m[2]])
        if not rows: raise ValueError('liste vide')
        file.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        return rows
    except Exception as e:
        if old: return old
        # The public Dolphin title index is an alternate source of the same Wii/GC IDs.
        if db=='wiitdb':
            try:
                req=urllib.request.Request('https://raw.githubusercontent.com/dolphin-emu/dolphin/master/Data/Sys/wiitdb-en.txt',headers={'User-Agent':'RetroVault catalogue metadata index'})
                with urllib.request.urlopen(req,timeout=30) as r: raw=r.read(8*1024*1024)
                rows=[[m[1],m[2]] for line in raw.decode('utf-8-sig',errors='replace').splitlines() if (m:=re.fullmatch(r'([A-Z0-9]{4,10})\s*=\s*(.{1,300})',line.strip()))]
                if rows:
                    file.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
                    return rows
            except Exception: pass
        raise RuntimeError(db+': '+str(e))
def region(id,kind):
    if kind=='ps3': return {'E':'EN','U':'US','J':'JA','K':'KO','A':'ZH','H':'US'}.get(id[2:3],'EN')
    return {'E':'US','P':'EN','J':'JA','K':'KO','F':'FR','D':'DE','I':'IT','S':'ES','U':'AU','A':'EN','X':'EN','Y':'EN','Z':'EN'}.get(id[3:4],'EN')
def index_gametdb(out,merged,base_title,write_json,alias_maps=None):
    alias_maps=alias_maps or {}
    output={}
    stats={'gametdb_platforms':0,'gametdb_matches':0,'gametdb_errors':[]}
    loaded={}
    for system,names in sorted(merged.items()):
        root=re.sub(r' \((?:Digital|PSN|Games on Demand|Download Play)\)$','',system,flags=re.I)
        if root not in SYSTEMS: continue
        kind,db,ext=SYSTEMS[root]
        if db not in loaded:
            try: loaded[db]=title_rows(db)
            except Exception as exc:
                loaded[db]=[]
                stats['gametdb_errors'].append(str(exc))
        pool=defaultdict(list)
        aliases=alias_maps.get(system,{})
        alias_pool=defaultdict(list)
        for id,title in loaded[db]:
            if db=='wiitdb':
                if root.endswith('GameCube') and not id.startswith('G'): continue
                if root.endswith('Wii') and (id.startswith('G') or len(id)!=6): continue
            if db=='ps3tdb' and not re.fullmatch(r'[BN][A-Z]{3}\d{5}',id): continue
            if db=='dstdb' and len(id)!=4: continue
            key=base_title(title)
            if key:
                pool[key].append(id)
                alias_pool[aliases.get(key,key)].append(id)
        index={}
        for title in sorted(names):
            key=base_title(title)
            ids=pool.get(key,[]) or alias_pool.get(aliases.get(key,key),[])
            if not ids: continue
            # Prefer the same region, then other documented editions of the exact normalized title.
            wanted='FR' if '(France' in title else 'EN' if '(Europe' in title else 'US' if '(USA' in title else 'JA' if '(Japan' in title else 'EN'
            ids=sorted(set(ids),key=lambda id:(region(id,kind)!=wanted,region(id,kind) not in ('EN','US'),id))
            index[title]=[[kind,region(id,kind),id,ext] for id in ids[:3]]
        if index:
            path='data/gametdb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
            write_json(out/path,index)
            output[system]=path
            stats['gametdb_matches']+=len(index)
    stats['gametdb_platforms']=len(output)
    return output,stats

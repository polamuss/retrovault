"""Index external cover references from the public OpenVGDB SQLite snapshot."""
import hashlib, json, re, sqlite3, tempfile, urllib.request, urllib.parse, zipfile
from collections import defaultdict, Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'.rv-image-cache'/'openvgdb-v29.json'
URL='https://github.com/OpenVGDB/OpenVGDB/releases/download/v29.0/openvgdb.zip'
HOSTS={'gamefaqs.gamespot.com','img.gamefaqs.net','gamefaqs.akamaized.net','www.gamefaqs.com','gamefaqs.com','www.mobygames.com','cdn.mobygames.com','images.launchbox-app.com'}
def safe_url(url):
    if not isinstance(url,str) or len(url)>800: return None
    try:
        p=urllib.parse.urlsplit(url)
        if p.scheme not in ('http','https') or p.hostname not in HOSTS or p.username or p.password or p.port or not re.search(r'\.(?:jpg|jpeg|png|webp)$',p.path,re.I): return None
        return urllib.parse.urlunsplit(('https',p.hostname,p.path,'',''))
    except ValueError: return None
def system_key(s):
    return re.sub(r'[^a-z0-9]','',s.casefold())
ALIASES={
 'Nintendo Entertainment System':'Nintendo - Nintendo Entertainment System','NES':'Nintendo - Nintendo Entertainment System',
 'Super Nintendo Entertainment System':'Nintendo - Super Nintendo Entertainment System','Super Nintendo':'Nintendo - Super Nintendo Entertainment System','SNES':'Nintendo - Super Nintendo Entertainment System',
 'Nintendo Famicom Disk System':'Nintendo - Family Computer Disk System','Famicom Disk System':'Nintendo - Family Computer Disk System','Nintendo Family Computer Disk System':'Nintendo - Family Computer Disk System',
 'Nintendo Game Boy':'Nintendo - Game Boy','Game Boy':'Nintendo - Game Boy','Nintendo Game Boy Color':'Nintendo - Game Boy Color','Game Boy Color':'Nintendo - Game Boy Color','Nintendo Game Boy Advance':'Nintendo - Game Boy Advance','Game Boy Advance':'Nintendo - Game Boy Advance',
 'Nintendo DS':'Nintendo - Nintendo DS','Nintendo Nintendo DS':'Nintendo - Nintendo DS','Nintendo 3DS':'Nintendo - Nintendo 3DS','Nintendo Nintendo 3DS':'Nintendo - Nintendo 3DS',
 'Nintendo 64':'Nintendo - Nintendo 64','Nintendo GameCube':'Nintendo - GameCube','Nintendo Wii':'Nintendo - Wii','Nintendo Virtual Boy':'Nintendo - Virtual Boy','Nintendo Pokemon Mini':'Nintendo - Pokemon Mini',
 'Sega Genesis':'Sega - Mega Drive - Genesis','Sega Mega Drive':'Sega - Mega Drive - Genesis','Sega Mega Drive Genesis':'Sega - Mega Drive - Genesis','Sega Master System':'Sega - Master System - Mark III','Sega CD':'Sega - Mega-CD - Sega CD','Sega Mega CD':'Sega - Mega-CD - Sega CD',
 'Sega 32X':'Sega - 32X','Sega Game Gear':'Sega - Game Gear','Sega Saturn':'Sega - Saturn','Sega Dreamcast':'Sega - Dreamcast','Sega SG-1000':'Sega - SG-1000',
 'Sony PlayStation':'Sony - PlayStation','Sony PlayStation 2':'Sony - PlayStation 2','Sony PlayStation Portable':'Sony - PlayStation Portable','Sony PSP':'Sony - PlayStation Portable','Sony PlayStation Vita':'Sony - PlayStation Vita',
 'NEC PC Engine':'NEC - PC Engine - TurboGrafx 16','NEC TurboGrafx-16':'NEC - PC Engine - TurboGrafx 16','NEC PC Engine TurboGrafx 16':'NEC - PC Engine - TurboGrafx 16','NEC TurboGrafx CD':'NEC - PC Engine CD - TurboGrafx-CD','NEC PC Engine CD':'NEC - PC Engine CD - TurboGrafx-CD',
 'SNK Neo Geo Pocket':'SNK - Neo Geo Pocket','SNK Neo Geo Pocket Color':'SNK - Neo Geo Pocket Color','SNK Neo Geo CD':'SNK - Neo Geo CD','SNK Neo Geo':'SNK - Neo Geo',
 'Atari 2600':'Atari - 2600','Atari 5200':'Atari - 5200','Atari 7800':'Atari - 7800','Atari Lynx':'Atari - Lynx','Atari Jaguar':'Atari - Jaguar','Atari Jaguar CD':'Atari - Jaguar CD',
 'Coleco ColecoVision':'Coleco - ColecoVision','ColecoVision':'Coleco - ColecoVision','Mattel Intellivision':'Mattel - Intellivision','Magnavox Odyssey2':'Magnavox - Odyssey2','GCE Vectrex':'GCE - Vectrex',
 'Bandai WonderSwan':'Bandai - WonderSwan','Bandai WonderSwan Color':'Bandai - WonderSwan Color','Commodore 64':'Commodore - 64','Commodore Amiga':'Commodore - Amiga','3DO':'The 3DO Company - 3DO','3DO Interactive Multiplayer':'The 3DO Company - 3DO','Microsoft Xbox':'Microsoft - Xbox','Microsoft Xbox 360':'Microsoft - Xbox 360'
}
def load_rows():
    try: return json.loads(CACHE.read_text(encoding='utf-8'))
    except (OSError,ValueError): pass
    CACHE.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        req=urllib.request.Request(URL,headers={'User-Agent':'RetroVault metadata index'})
        with urllib.request.urlopen(req,timeout=60) as r:
            data=r.read(50_000_001)
        if len(data)>50_000_000: raise ValueError('archive trop grande')
        archive=tmp/'db.zip'
        archive.write_bytes(data)
        with zipfile.ZipFile(archive) as z:
            files=[]
            for info in z.infolist():
                if info.is_dir() or info.file_size<100 or info.file_size>500_000_000: continue
                with z.open(info) as member:
                    if member.read(16)==b'SQLite format 3\x00': files.append(info)
            db=tmp/'db.sqlite'
            import shutil
            found=False
            for info in files:
                with z.open(info) as src,db.open('wb') as dst: shutil.copyfileobj(src,dst)
                with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as conn:
                    tables={row[0].lower() for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {'roms','releases','systems'}.issubset(tables):
                    found=True
                    break
            if not found: raise ValueError('base SQLite OpenVGDB compatible absente')
        with sqlite3.connect('file:'+str(db)+'?mode=ro',uri=True) as conn:
            rows=conn.execute('SELECT DISTINCT s.systemName, r.releaseTitleName, rom.romFileName, r.releaseCoverFront FROM ROMs rom JOIN RELEASES r USING (romID) JOIN SYSTEMS s USING (systemID) WHERE r.releaseCoverFront IS NOT NULL').fetchall()
        counts=Counter()
        result=[]
        for system,title,filename,url in rows:
            if not isinstance(system,str) or not isinstance(title,str): continue
            url=safe_url(url)
            if not url: continue
            filename=re.sub(r'\.(?:zip|7z|nes|sfc|smc|gb|gbc|gba|n64|z64|v64|nds|bin|iso|cue|chd|md|gen|sms|gg|pce|a26|a78|lnx|j64|ws|wsc|rom)$','',str(filename or ''),flags=re.I)
            result.append([system,title,filename,url])
            counts[system]+=1
        CACHE.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return result
def steam_rows():
    cache=ROOT/'.rv-image-cache'/'steam-appdb-games-v1.json'
    import time
    try:
        if time.time()-cache.stat().st_mtime<14*86400: return json.loads(cache.read_text(encoding='utf-8'))
    except (OSError,ValueError): pass
    url='https://raw.githubusercontent.com/Austrum-lab/steam-appdb/master/data/game.json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'RetroVault metadata index'}),timeout=60) as response:
            raw=response.read(32*1024*1024+1)
        if len(raw)>32*1024*1024: raise ValueError('Steam index too large')
        data=json.loads(raw)
        rows=[[str(r['appid']),r['name']] for r in data if isinstance(r,dict) and str(r.get('appid','')).isdigit() and isinstance(r.get('name'),str)]
        if not rows: raise ValueError('Steam index empty')
        cache.parent.mkdir(parents=True,exist_ok=True)
        cache.write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        return rows
    except Exception:
        if cache.is_file(): return json.loads(cache.read_text(encoding='utf-8'))
        raise

def index_steam(merged,base_title):
    systems=[s for s in merged if system_key(s) in ('windows','microsoftwindows','pc','pcwindows','microsoftpc','microsoftwindowsdigital','windowsdigital')]
    if not systems: return {}
    pool=defaultdict(set)
    for appid,title in steam_rows():
        key=base_title(title)
        if key: pool[key].add(appid)
    result={}
    for system in systems:
        refs={}
        for title in merged[system]:
            key=base_title(title)
            ids=pool.get(key,set())
            if len(key)>=4 and len(ids)==1:
                appid=next(iter(ids))
                refs[title]=['https://cdn.cloudflare.steamstatic.com/steam/apps/'+appid+'/library_600x900.jpg']
        if refs: result[system]=refs
    return result

def index_openvgdb(out,merged,base_title,write_json,alias_maps=None):
    alias_maps=alias_maps or {}
    stats={'openvgdb_source_rows':0,'openvgdb_matches':0,'openvgdb_platforms':0,'openvgdb_unmapped':[],'openvgdb_error':None}
    result={}
    try: rows=load_rows()
    except Exception as e:
        stats['openvgdb_error']=str(e)
        rows=[]
    stats['openvgdb_source_rows']=len(rows)
    targets={system_key(s):s for s in merged}
    targets.update({system_key(a):s for a,s in ALIASES.items() if s in merged})
    pools=defaultdict(lambda:defaultdict(set))
    unknown=set()
    for system,title,filename,url in rows:
        sys=targets.get(system_key(system))
        if not sys:
            unknown.add(system);continue
        for key in {base_title(title),base_title(filename)}-{''}:
            pools[sys][key].add(url)
    stats['openvgdb_unmapped']=sorted(unknown)
    for system,names in sorted(merged.items()):
        root=re.sub(r' \((?:Digital|PSN|Games on Demand|Download Play)\)$','',system,flags=re.I)
        pool=pools.get(system) or pools.get(root)
        if not pool: continue
        index={}
        aliases={**alias_maps.get(root,{}),**alias_maps.get(system,{})}
        alias_pool=defaultdict(set)
        for key,urls in pool.items(): alias_pool[aliases.get(key,key)].update(urls)
        for title in sorted(names):
            key=base_title(title)
            hits=pool.get(key,set()) or alias_pool.get(aliases.get(key,key),set())
            if not hits:
                stripped=re.sub(r'\s*\((?:19\d{2}|20\d{2})(?:\s*[-,]\s*[^)]*)?\)(?:\s*\([^)]*\))*\s*
            if hits: index[title]=sorted(hits)[:3]
        if index:
            path='data/openvgdb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
            write_json(out/path,index)
            result[system]=path
            stats['openvgdb_matches']+=len(index)
    stats['openvgdb_platforms']=len(result)
    stats['steam_bulk_matches']=0
    try:
        for system,refs in index_steam(merged,base_title).items():
            path=result.get(system,'data/openvgdb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json')
            existing=json.loads((out/path).read_text(encoding='utf-8')) if system in result else {}
            for title,urls in refs.items():
                if title not in existing:
                    existing[title]=urls
                    stats['steam_bulk_matches']+=1
            write_json(out/path,existing)
            result[system]=path
    except Exception as e:
        stats['steam_bulk_error']=str(e)
    return result,stats
,'',title)
                k=base_title(stripped)
                if stripped!=title and len(k)>=5: hits=pool.get(k,set()) or alias_pool.get(aliases.get(k,k),set())
            if hits: index[title]=sorted(hits)[:3]
        if index:
            path='data/openvgdb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
            write_json(out/path,index)
            result[system]=path
            stats['openvgdb_matches']+=len(index)
    stats['openvgdb_platforms']=len(result)
    return result,stats

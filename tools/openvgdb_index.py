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
            files=[i for i in z.infolist() if i.filename.lower().endswith('.sqlite') and i.file_size<500_000_000]
            if len(files)!=1: raise ValueError('base SQLite absente ou ambiguë')
            db=tmp/'db.sqlite'
            db.write_bytes(z.read(files[0]))
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
def index_openvgdb(out,merged,base_title,write_json):
    stats={'openvgdb_source_rows':0,'openvgdb_matches':0,'openvgdb_platforms':0,'openvgdb_unmapped':[],'openvgdb_error':None}
    result={}
    try: rows=load_rows()
    except Exception as e:
        stats['openvgdb_error']=str(e);return result,stats
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
        for title in sorted(names):
            hits=pool.get(base_title(title),set())
            if hits: index[title]=sorted(hits)[:3]
        if index:
            path='data/openvgdb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
            write_json(out/path,index)
            result[system]=path
            stats['openvgdb_matches']+=len(index)
    stats['openvgdb_platforms']=len(result)
    return result,stats

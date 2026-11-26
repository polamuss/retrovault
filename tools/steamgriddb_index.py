"""Optional, bounded SteamGridDB lookup of public artwork links. Never save credentials."""
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, Counter, deque
from pathlib import Path
from build import base_title, extract_array, norm
from launchbox_index import ALIASES as LB_ALIASES

API='https://www.steamgriddb.com/api/v2/'
CACHE=Path('.rv-image-cache/steamgriddb-links-v1.json')
MAX_TITLES=300
MAX_REQUESTS=450
MAX_SECONDS=900
RETRY_DAYS=30
API_CALLS=0
DEADLINE=0
API_STOP_REASON=''
HOSTS={'cdn.steamgriddb.com','cdn2.steamgriddb.com'}
class StopLookup(Exception): pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None
OPENER=urllib.request.build_opener(NoRedirect())
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,obj):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
def public_image(url):
    if not isinstance(url,str) or len(url)>500: return None
    try:
        u=urllib.parse.urlsplit(url)
        if u.scheme!='https' or u.netloc not in HOSTS or u.query or u.fragment or not re.fullmatch(r'/grid/[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp)',u.path,re.I): return None
        return url
    except ValueError: return None
def api(path,key):
    global API_CALLS, API_STOP_REASON
    if API_CALLS>=MAX_REQUESTS or time.monotonic()>=DEADLINE:
        API_STOP_REASON='budget';raise StopLookup()
    API_CALLS+=1
    time.sleep(1)
    req=urllib.request.Request(API+path,headers={'Authorization':'Bearer '+key,'Accept':'application/json','User-Agent':'RetroVault artwork reference lookup'})
    try:
        with OPENER.open(req,timeout=12) as res:
            raw=res.read(2_000_001)
        if len(raw)>2_000_000: raise StopLookup()
        data=json.loads(raw)
        if data.get('success') is not True: raise StopLookup()
        return data.get('data',[])
    except urllib.error.HTTPError as e:
        if e.code==404: return []
        API_STOP_REASON='http_'+str(e.code)
        raise StopLookup() from None
    except (OSError,ValueError): raise StopLookup() from None
def clean_title(title):
    # Strip only annotations already recognized by the catalogue normalizer.
    original=base_title(title)
    while True:
        shorter=re.sub(r'\s*(?:\([^()]*\)|\[[^\[\]]*\])\s*$','',title).strip()
        if shorter==title or not shorter or base_title(shorter)!=original: break
        title=shorter
    m=re.match(r'^(.*), (The|A|An)(?=\s*[-:]|$)(.*)$',title,re.I)
    if m: title=m[2]+' '+m[1]+m[3]
    return re.sub(r'\s+',' ',title).strip()

def variants(names):
    result=[]
    for n in names:
        title=clean_title(n)
        plain=''.join(c for c in unicodedata.normalize('NFKD',title) if not unicodedata.combining(c))
        soft=re.sub(r'[™®©]','',plain).strip()
        for v in (title,soft,re.sub(r'[^\w\s]',' ',soft)):
            v=' '.join(v.split())
            if v and v.casefold() not in {x.casefold() for x in result}: result.append(v)
    return result[:4]

def family(system):
    return re.sub(r' \((?:Digital|PSN|Games on Demand|Download Play)\)$','',system,flags=re.I)

def load_aliases(snapshot,stats):
    # Read the already generated LaunchBox cache only. No additional authenticated request.
    import gzip
    root=Path(__file__).resolve().parents[1]
    file=root/'.rv-image-cache'/'launchbox-index-v3.json.gz'
    if not file.is_file(): return {}
    try:
        with gzip.open(file,'rt',encoding='utf-8') as f: data=json.load(f)
        platforms=extract_array((root/'index.html').read_text(encoding='utf-8'),'const explorePlatforms=')
        targets=defaultdict(set)
        for sys in snapshot: targets[norm(sys)].add(sys)
        for p in platforms:
            sys=p.get('system')
            if sys not in snapshot or p.get('parent'): continue
            for n in (p['name'],p.get('brand','')+' '+p['name']): targets[norm(n)].add(sys)
        result=defaultdict(lambda:defaultdict(set))
        for name,rows in data.get('platforms',{}).items():
            sys=LB_ALIASES.get(name)
            if sys not in snapshot:
                matches=targets.get(norm(name),set())
                sys=next(iter(matches)) if len(matches)==1 else None
            if not sys: continue
            for title,aliases,_ in rows:
                if not isinstance(title,str): continue
                names=[n for n in [title,*aliases] if isinstance(n,str)]
                canonical=base_title(title)
                if canonical:
                    result[sys][canonical].update(names)
        stats['launchbox_alias_groups']=sum(map(len,result.values()))
        return result
    except Exception:
        stats['launchbox_alias_cache_unavailable']+=1
        return {}

def acceptable_hit(g,keys,shared):
    if not isinstance(g,dict) or not isinstance(g.get('name'),str) or type(g.get('id')) is not int: return False
    if base_title(g['name']) not in keys: return False
    if 'software' in (g.get('types') or []): return False
    # Short or cross-platform matches require the database's verified flag.
    if (shared or len(base_title(g['name']))<4) and g.get('verified') is not True: return False
    return True

def find(names,key,stats,shared=False):
    keys={base_title(n) for n in names}-{''}
    ids={}
    for title in variants(names):
        data=api('search/autocomplete/'+urllib.parse.quote(title,safe=''),key)
        if not isinstance(data,list):
            stats['invalid_search_response']+=1
            continue
        hits=[g for g in data if acceptable_hit(g,keys,shared)]
        for g in hits: ids[g['id']]=g
        if ids: break
    if not ids:
        stats['no_exact_title']+=1
        return []
    if len(ids)!=1:
        stats['ambiguous_title']+=1
        return []
    id=next(iter(ids))
    # No dimensions restriction: accept all safe static portrait formats.
    data=api('grids/game/'+str(id)+'?types=static&nsfw=false&humor=false&epilepsy=false',key)
    if not isinstance(data,list) or not data:
        stats['no_grid']+=1
        return []
    results=[]
    for g in data:
        if not isinstance(g,dict) or g.get('nsfw') is not False or g.get('humor') is not False or g.get('epilepsy') is True: continue
        if g.get('mime') and g['mime'] not in ('image/png','image/jpeg','image/webp'): continue
        w,h=g.get('width'),g.get('height')
        if type(w) is not int or type(h) is not int or not 0<w<h: continue
        url=public_image(g.get('thumb')) or public_image(g.get('url'))
        if url and url not in results: results.append(url)
        if len(results)>=2: break
    stats['accepted' if results else 'grid_rejected']+=1
    return results

def main():
    out=Path(sys.argv[1])
    index=read(out/'data/index.json')
    report=read(out/'data/report.json')
    try: cached=read(CACHE)
    except (OSError,ValueError): cached={}
    if not isinstance(cached,dict): cached={}
    key=os.environ.get('STEAMGRIDDB_API_KEY','').strip()
    snapshot=read(out/index['catalog_snapshot'])
    stats=Counter()
    lb_names=load_aliases(snapshot,stats) if key else {}
    # Track title families to distinguish digital editions from genuinely different platforms.
    owners=defaultdict(set)
    for system,row in snapshot.items():
        for name in row[0]:
            owners[row[1].get(base_title(name),base_title(name))].add(family(system))
    jobs=[]
    existing={}
    for system,row in snapshot.items():
        names,aliases=row
        seen=set()
        for field in ('art','launchbox_art','gametdb_art','openvgdb_art'):
            path=index.get(field,{}).get(system)
            if path:
                data=read(out/path)
                if field=='art': data=data.get('rows',{})
                seen.update(aliases.get(base_title(n),base_title(n)) for n in data)
        existing[system]=seen
        groups=defaultdict(list)
        for n in names: groups[aliases.get(base_title(n),base_title(n))].append(n)
        for group,versions in groups.items():
            if group in seen or not group: continue
            official=sorted(lb_names.get(system,{}).get(group,()),key=lambda n:(base_title(n)!=group,len(n),n))
            shared=len(owners[group])>1
            # For different hardware families require documented official names on both sides.
            if shared:
                families=owners[group]
                documented={family(other) for other,mapping in lb_names.items() if group in mapping}
                if not official or not families.issubset(documented):
                    stats['unverified_multiplatform']+=1
                    continue
            names=[*official,*sorted(versions,key=lambda n:(base_title(n)!=group,len(n),n))]
            names=[n for n in names if not re.search(r'\b(?:demo|prototype|beta|sample|test program|bios|firmware|trainer|rom hack)\b',clean_title(n),re.I)]
            if not names: continue
            title=clean_title(names[0])
            if not title: continue
            # Prefer real documented releases, then games with multiple editions.
            priority=(not bool(official),-min(len(versions),10),title.casefold())
            jobs.append((system,group,names[:12],shared,priority))
    # Spread the sample over all platforms instead of exhausting the first one.
    batches=defaultdict(deque)
    for system,group,names,shared,priority in sorted(jobs,key=lambda row:row[4]): batches[system].append((system,group,names,shared))
    ordered=[]
    while batches:
        for system in list(batches):
            ordered.append(batches[system].popleft())
            if not batches[system]: del batches[system]
    attempted=0
    stopped=False
    global DEADLINE
    DEADLINE=time.monotonic()+MAX_SECONDS
    now=int(time.time())
    if key:
        for system,group,names,shared in ordered:
            token=system+'|'+group
            old=cached.get(token)
            if isinstance(old,list) and old: continue
            if isinstance(old,dict) and (old.get('links') or now-old.get('checked',0)<RETRY_DAYS*86400): continue
            if attempted>=MAX_TITLES or API_CALLS>=MAX_REQUESTS or time.monotonic()>=DEADLINE: break
            attempted+=1
            try:
                links=find(names,key,stats,shared)
                cached[token]={'links':links,'checked':now}
                if attempted%10==0: write(CACHE,cached)
            except StopLookup:
                stopped=True
                break
        write(CACHE,cached)
    # Only public CDN links are stored, no API response or account information.
    paths={}
    editions=0
    groups_added=0
    for system,row in snapshot.items():
        names,aliases=row
        rows={}
        groups=set()
        for name in names:
            group=aliases.get(base_title(name),base_title(name))
            if group in existing[system]: continue
            values=cached.get(system+'|'+group,[])
            if isinstance(values,dict): values=values.get('links',[])
            if not isinstance(values,list): continue
            links=[u for v in values if (u:=public_image(v))][:2]
            if links:
                rows[name]=links
                groups.add(group)
        if rows:
            path='data/steamgriddb/'+hashlib.sha256(system.encode()).hexdigest()[:16]+'.json'
            write(out/path,rows)
            paths[system]=path
            editions+=len(rows)
            groups_added+=len(groups)
    index['steamgriddb_art']=paths
    report.update(steamgriddb_additional_editions=editions,steamgriddb_additional_groups=groups_added,steamgriddb_lookups_this_run=attempted,steamgriddb_api_stopped=stopped,steamgriddb_lookup_results=dict(stats),steamgriddb_eligible_titles=len(jobs),steamgriddb_api_requests=API_CALLS,steamgriddb_stop_reason=API_STOP_REASON)
    report['game_editions_with_image_reference']+=editions
    report['game_editions_without_image_reference']-=editions
    report['game_title_groups_with_image_reference']+=groups_added
    for _ in range(3):
        report['site_bytes']=sum(p.stat().st_size for p in out.rglob('*') if p.is_file())
        index['report']=report
        write(out/'data/index.json',index)
        write(out/'data/report.json',report)
    print('SteamGridDB diagnostics: '+json.dumps(dict(stats),sort_keys=True))
    print('SteamGridDB: '+str(attempted)+' titres interrogés, '+str(groups_added)+' groupes supplémentaires. Arrêt API: '+str(stopped))
    if report['site_bytes']>950_000_000: raise SystemExit('Site trop volumineux')
if __name__=='__main__': main()

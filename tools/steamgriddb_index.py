"""Optional, bounded SteamGridDB lookup of public artwork links. Never save credentials."""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, Counter, deque
from pathlib import Path
from build import base_title

API='https://www.steamgriddb.com/api/v2/'
CACHE=Path('.rv-image-cache/steamgriddb-links-v1.json')
MAX_TITLES=150
MAX_SECONDS=600
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
        raise StopLookup() from None
    except (OSError,ValueError): raise StopLookup() from None
def find(title,key,stats):
    data=api('search/autocomplete/'+urllib.parse.quote(title,safe=''),key)
    if not isinstance(data,list):
        stats['invalid_search_response']+=1
        return []
    hits=[g for g in data if isinstance(g,dict) and isinstance(g.get('name'),str) and base_title(g['name'])==base_title(title) and type(g.get('id')) is int]
    if not hits:
        stats['no_exact_title']+=1
        return []
    if len({g['id'] for g in hits})!=1:
        stats['ambiguous_title']+=1
        return []
    id=hits[0]['id']
    data=api('grids/game/'+str(id)+'?dimensions=600x900,342x482,660x930&types=static&nsfw=false&humor=false&epilepsy=false',key)
    if not isinstance(data,list) or not data:
        stats['no_grid']+=1
        return []
    results=[]
    for g in data:
        if not isinstance(g,dict) or g.get('nsfw') is not False or g.get('humor') is not False or g.get('epilepsy') is True: continue
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
    # Do not match generic titles shared across different platforms by name alone.
    owners=defaultdict(set)
    for system,row in snapshot.items():
        for name in row[0]:
            owners[base_title(name)].add(system)
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
            if group in seen or len(group)<6 or len(owners[group])!=1: continue
            # Query an unqualified title only, not a regional filename.
            title=min(versions,key=lambda n:(len(n),n))
            title=re.sub(r'(?:\s*(?:\([^()]*\)|\[[^\[\]]*\]))+$','',title).strip()
            if base_title(title)!=group: continue
            if re.search(r'\b(?:demo|prototype|beta|sample|test program|bios|firmware|trainer|rom hack)\b',title,re.I): continue
            jobs.append((system,group,title))
    # Spread the sample over all platforms instead of exhausting the first one.
    batches=defaultdict(deque)
    for system,group,title in jobs: batches[system].append((system,group,title))
    ordered=[]
    while batches:
        for system in list(batches):
            ordered.append(batches[system].popleft())
            if not batches[system]: del batches[system]
    attempted=0
    stopped=False
    stats=Counter()
    deadline=time.monotonic()+MAX_SECONDS
    if key:
        for system,group,title in ordered:
            token=system+'|'+group
            if token in cached: continue
            if attempted>=MAX_TITLES or time.monotonic()>=deadline: break
            attempted+=1
            try: cached[token]=find(title,key,stats)
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
    report.update(steamgriddb_additional_editions=editions,steamgriddb_additional_groups=groups_added,steamgriddb_lookups_this_run=attempted,steamgriddb_api_stopped=stopped,steamgriddb_lookup_results=dict(stats),steamgriddb_eligible_titles=len(jobs))
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

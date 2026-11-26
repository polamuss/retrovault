"""Fail closed if configured credentials appear in a public deployment."""
import os
import sys
from pathlib import Path

def main():
    root=Path(sys.argv[1])
    if not root.is_dir():
        raise SystemExit('Public output directory missing')
    secrets=[os.environ.get(k,'').encode('utf-8') for k in ('RV_CHECK_IGDB_ID','RV_CHECK_IGDB_SECRET')]
    secrets=[s for s in secrets if len(s)>=12]
    if not secrets:
        print('No IGDB credentials configured for publication check.')
        return
    overlap=max(map(len,secrets))-1
    matches=0
    for p in root.rglob('*'):
        if not p.is_file(): continue
        with p.open('rb') as f:
            tail=b''
            while chunk:=f.read(1024*1024):
                data=tail+chunk
                if any(s in data for s in secrets):
                    matches+=1
                    break
                tail=data[-overlap:]
    if matches:
        raise SystemExit('Publication blocked: confidential credential found in public output.')
    print('Public output: no configured IGDB credentials found.')

if __name__=='__main__': main()

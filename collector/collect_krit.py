#!/usr/bin/env python3
"""KRIT public board collector. HTML selectors verified against user-saved 2026-11 pages.
Does not download attachments. A live GitHub Actions run is required for network verification.
"""
import json, re, sys, time
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlparse
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/krit.json'
BASE='https://www.krit.re.kr/krit/bbs/'
BOARDS={'notice':('공지사항','사업공고·공지'),'regulatory':('규정자료','규정·지침'),'press':('보도자료','정책·기술 동향')}
PAGES=3  # 3 pages per board per run; adjust after live verification
MAX_BYTES=3_000_000
PAT=re.compile(r"fnView\(\s*'([a-z]+)'\s*,\s*'[^']*'\s*,\s*'(\d+)'",re.I)

def fetch(url):
    req=Request(url,headers={'User-Agent':'NJ-STRATEGY-HUB-ResearchFeed/1.0 (public board metadata)','Accept':'text/html'})
    with urlopen(req,timeout=20) as resp:
        if urlparse(resp.geturl()).hostname not in ('www.krit.re.kr','krit.re.kr') or resp.geturl().split(':',1)[0]!='https':
            raise ValueError('Unexpected redirect')
        raw=resp.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:raise ValueError('HTML size limit exceeded')
        return raw.decode('utf-8','replace')

def parse_list(html,board):
    soup=BeautifulSoup(html,'html.parser')
    result=[]
    for li in soup.select('ul.listType > li'):
        a=li.find('a',onclick=True)
        if not a:continue
        m=PAT.search(a.get('onclick',''))
        if not m or m.group(1)!=board:continue
        title=a.get_text(' ',strip=True)
        title=re.sub(r'^\s*(?:공지|\d+)\s+','',title).strip()
        if not title:continue
        date=li.select_one('li.date')
        published=date.get_text(' ',strip=True) if date else ''
        ntt=m.group(2)
        result.append({'title':title[:500],'agency':'국방기술진흥연구소',
          'url':f'{BASE}{board}_view.do?bbsId={board}&nttId={ntt}',
          'publishedAt':published,'summary':'','type':BOARDS[board][1],
          'domains':['국방·방산'],'keywords':[BOARDS[board][0]],
          'board':board,'sourceId':ntt,'hasAttachment':bool(li.select_one('.file'))})
    return result

def main():
    old={}
    if OUTPUT.exists():
        try:
            for r in json.loads(OUTPUT.read_text(encoding='utf-8')).get('items',[]):
                if r.get('url'):old[r['url'].lower()]=r
        except (ValueError,TypeError):pass
    merged=dict(old); warnings=[]; board_counts={}; success=0
    for board in BOARDS:
        count=0
        for page in range(1,PAGES+1):
            url=f'{BASE}{board}_list.do?{urlencode({"page":page})}'
            try:
                records=parse_list(fetch(url),board)
                if not records:
                    warnings.append(f'{board} page {page}: no records parsed; verify page structure')
                    break
                for r in records:
                    key=r['url'].lower()
                    prev=merged.get(key,{})
                    # Preserve previously collected richer metadata.
                    if prev.get('summary'):r['summary']=prev['summary']
                    merged[key]=r
                count+=len(records)
                if page<PAGES:time.sleep(0.5)
            except Exception as exc:
                warnings.append(f'{board} page {page}: {type(exc).__name__}: {exc}')
                break
        board_counts[board]=count
        if count:success+=1
    if success==0:
        print('No KRIT boards parsed; existing output left unchanged',file=sys.stderr)
        for w in warnings:print(w,file=sys.stderr)
        return 1
    data={'schema':'nj-krit-feed-v1','generatedAt':datetime.now(timezone.utc).isoformat(),
      'agency':'국방기술진흥연구소','successfulBoards':success,'boardCounts':board_counts,
      'warnings':warnings,'items':sorted(merged.values(),key=lambda r:(r.get('publishedAt',''),r.get('title','')),reverse=True)[:5000]}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'KRIT boards {success}/3, records {len(data["items"])}; warnings {len(warnings)}')
    for w in warnings:print('WARNING:',w)
    return 0

if __name__=='__main__':sys.exit(main())

"""NJ public G2B procurement feed collector. No third-party dependencies."""
import json, os, hashlib, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST=timezone(timedelta(hours=9))
BASE='https://apis.data.go.kr/1230000/ad/BidPublicInfoService02/getBidPblancListInfoServc02'
KEYWORDS=['국방','군수','정비','무기체계','드론','무인기','대드론','획득','방산','군사','전력지원','MRO','연구용역','에너지','태양광','AI','인공지능','기술사업화','민군','국방시설','시험평가']
STRONG=['국방','군수','정비','무기체계','드론','무인기','대드론','획득','방산','군사','전력지원','MRO','민군','국방시설']
OUTPUT=Path(__file__).resolve().parent.parent/'docs'/'notices.json'

def request_page(key,begin,end,page):
    args={'serviceKey':key,'pageNo':page,'numOfRows':100,'inqryDiv':1,'inqryBgnDt':begin,'inqryEndDt':end,'type':'json'}
    url=BASE+'?'+urllib.parse.urlencode(args)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'NJ-Strategy-Hub/1.0'}),timeout=35) as res:
        data=json.load(res)
    envelope=data.get('response',{})
    header=envelope.get('header',{})
    if str(header.get('resultCode','00')) not in ('00','0'):
        raise RuntimeError('G2B API error: '+str(header.get('resultMsg','unknown')))
    body=envelope.get('body',{})
    items=body.get('items') or []
    if isinstance(items,dict):items=items.get('item',[])
    if isinstance(items,dict):items=[items]
    return items,int(body.get('totalCount',len(items)))

def normalize(r):
    title=str(r.get('bidNtceNm') or '').strip()
    number=str(r.get('bidNtceNo') or '').strip()
    order=str(r.get('bidNtceOrd') or '').strip()
    agency=str(r.get('ntceInsttNm') or r.get('dminsttNm') or '').strip()
    text=title+' '+agency
    hits=[w for w in KEYWORDS if w.casefold() in text.casefold()]
    if not hits:return None
    relevance=min(100, (50 if any(w.casefold() in text.casefold() for w in STRONG) else 20)+min(45,15*len(hits)))
    raw_date=str(r.get('bidNtceDt') or '')
    due=str(r.get('bidClseDt') or r.get('bidClseDtTime') or '')
    url=str(r.get('bidNtceDtlUrl') or '').strip()
    if not url.startswith('https://'):url=''
    return {'source':'나라장터','noticeNumber':number,'noticeOrder':order,'title':title,'agency':agency,
            'publishedAt':raw_date,'due':due,'budget':str(r.get('presmptPrce') or r.get('asignBdgtAmt') or ''),
            'url':url,'keywords':hits,'relevance':relevance,'sourceStatus':'원문 확인 필요',
            'externalId':'g2b:'+number+':'+order}

def main():
    key=os.getenv('DATA_GO_KR_SERVICE_KEY','').strip()
    if not key:raise RuntimeError('GitHub Actions secret DATA_GO_KR_SERVICE_KEY is not set')
    now=datetime.now(KST); start=now-timedelta(days=2)
    begin=start.strftime('%Y%m%d%H%M');end=now.strftime('%Y%m%d%H%M')
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    previous={}
    if OUTPUT.exists():
        try:previous={x['externalId']:x for x in json.loads(OUTPUT.read_text(encoding='utf-8')).get('items',[])}
        except (ValueError,KeyError,TypeError):pass
    current={};page=1
    while True:
        items,total=request_page(key,begin,end,page)
        for item in items:
            row=normalize(item)
            if row:current[row['externalId']]=row
        if page*100>=total or not items:break
        page+=1
        if page>100:raise RuntimeError('Too many pages; refusing to publish incomplete feed')
    for id_,row in current.items():
        old=previous.get(id_)
        if old:
            old_hash=hashlib.sha256(json.dumps({k:v for k,v in old.items() if k not in ('changeStatus','firstSeen','lastSeen')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            new_hash=hashlib.sha256(json.dumps(row,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            row['changeStatus']='변경 확인 필요' if old_hash!=new_hash else old.get('changeStatus','기존')
            row['firstSeen']=old.get('firstSeen',now.isoformat())
        else:row['changeStatus']='신규';row['firstSeen']=now.isoformat()
        row['lastSeen']=now.isoformat()
    previous.update(current)
    # Keep a bounded history of candidate notices for feed size and retention.
    all_items=sorted(previous.values(),key=lambda r:r.get('lastSeen',''),reverse=True)[:2000]
    payload={'schema':'nj-notice-feed-v1','generatedAt':now.isoformat(),'source':'조달청 나라장터 용역 API',
             'scope':'최근 2일 수집 + 이전 후보 최대 2000건','items':all_items}
    tmp=OUTPUT.with_suffix('.tmp');tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(OUTPUT)
    print(f'Fetched {len(current)} matching notices, published {len(all_items)}')

if __name__=='__main__':
    try:main()
    except Exception as e:print(f'Collection failed: {e}',file=sys.stderr);sys.exit(1)

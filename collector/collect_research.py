#!/usr/bin/env python3
"""Public RSS/Atom -> NJ research feed. No third-party dependencies.
Sources require explicit verification and configuration; no speculative crawling.
"""
import json, re, hashlib, os, sys
from pathlib import Path
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'collector/research_sources.json'
OUTPUT = ROOT / 'docs/research.json'
MAX_ITEMS = 5000
MAX_BYTES = 3_000_000

def tagname(el): return el.tag.rsplit('}', 1)[-1]
def child_text(el, names):
    for node in el:
        if tagname(node) in names and (node.text or '').strip(): return node.text.strip()
    return ''
def safe_https(url):
    p = urlparse(url or '')
    return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password

def parse_feed(content, source):
    root = ET.fromstring(content)
    records = []
    for item in root.iter():
        if tagname(item) not in ('item','entry'): continue
        title = child_text(item, ('title',))
        link = child_text(item, ('link',))
        if not link:
            for el in item:
                if tagname(el) == 'link' and el.attrib.get('href') and el.attrib.get('rel', 'alternate') == 'alternate':
                    link = el.attrib['href']; break
        if not title or not safe_https(link): continue
        summary = child_text(item, ('summary','description','content','encoded'))
        summary = re.sub(r'<[^>]*>', ' ', summary)
        summary = re.sub(r'\s+', ' ', summary).strip()[:4000]
        published = child_text(item, ('published','updated','pubDate','date'))
        records.append({'title':title[:500], 'agency':source['agency'][:200], 'url':link[:2000],
                        'publishedAt':published[:80], 'summary':summary,
                        'type':source.get('type','연구·정책 자료'),
                        'domains':source.get('domains',[])[:10], 'keywords':source.get('keywords',[])[:30]})
    return records

def main():
    conf = json.loads(CONFIG.read_text(encoding='utf-8'))
    sources = conf.get('sources', [])
    if not isinstance(sources, list): raise ValueError('sources must be an array')
    old = {}
    if OUTPUT.exists():
        try:
            for r in json.loads(OUTPUT.read_text(encoding='utf-8')).get('items',[]):
                if safe_https(r.get('url')): old[r['url'].lower()] = r
        except (ValueError, KeyError, TypeError): pass
    merged = dict(old)
    # Merge KRIT board records when available; keep the RSS/Atom schema unchanged.
    krit_file = ROOT / 'docs/krit.json'
    if krit_file.exists():
        try:
            krit = json.loads(krit_file.read_text(encoding='utf-8'))
            for r in krit.get('items', []):
                if safe_https(r.get('url')):
                    key = r['url'].lower()
                    previous = merged.get(key, {})
                    merged[key] = {**previous, **r}
        except (ValueError, TypeError, KeyError) as exc:
            print(f'KRIT merge warning: {exc}', file=sys.stderr)
    failures=[]; successes=0
    for src in sources:
        url = src.get('url','')
        if not safe_https(url) or not src.get('agency'):
            failures.append('Invalid source configuration: HTTPS URL and agency required'); continue
        try:
            req=Request(url,headers={'User-Agent':'NJ-STRATEGY-HUB-ResearchFeed/1.0','Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml'})
            with urlopen(req,timeout=18) as response:
                if not safe_https(response.geturl()): raise ValueError('Insecure redirect')
                raw=response.read(MAX_BYTES+1)
            if len(raw)>MAX_BYTES: raise ValueError('Feed size limit exceeded')
            parsed=parse_feed(raw,src)
            for record in parsed: merged[record['url'].lower()]=record
            successes+=1
            print(f"{src['agency']}: {len(parsed)} entries")
        except Exception as exc:
            failures.append(f"{src.get('agency','unknown')}: {type(exc).__name__}: {exc}")
    # Do not overwrite an existing valid feed when all configured sources fail.
    if sources and successes==0 and not (krit_file.exists() and merged != old):
        print('All sources failed; keeping existing research.json',file=sys.stderr)
        for msg in failures: print(msg,file=sys.stderr)
        return 1
    records=sorted(merged.values(),key=lambda x:(x.get('publishedAt',''),x.get('title','')),reverse=True)[:MAX_ITEMS]
    data={'schema':'nj-research-feed-v1','generatedAt':datetime.now(timezone.utc).isoformat(),
          'source':'Configured public RSS/Atom feeds','configuredSources':len(sources),
          'successfulSources':successes,'warnings':failures,'items':records}
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    OUTPUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Published {len(records)} research records; {len(failures)} warnings')
    return 0

if __name__=='__main__': sys.exit(main())

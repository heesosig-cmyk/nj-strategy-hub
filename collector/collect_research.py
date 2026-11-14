#!/usr/bin/env python3
"""Collect configured public RSS/Atom feeds and merge KRIT board records.

KRIT identity is board + sourceId, not URL. Historical detail links are
retained as metadata, while the user-facing link points to the board list.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'collector/research_sources.json'
OUTPUT = ROOT / 'docs/research.json'
KRIT_FILE = ROOT / 'docs/krit.json'
MAX_ITEMS = 5000
MAX_BYTES = 3_000_000
KRIT_HOSTS = {'krit.re.kr', 'www.krit.re.kr'}
BOARDS = {'notice', 'regulatory', 'press'}


def tagname(el):
    return el.tag.rsplit('}', 1)[-1]


def child_text(el, names):
    for node in el:
        if tagname(node) in names and (node.text or '').strip():
            return node.text.strip()
    return ''


def safe_https(url):
    p = urlparse(url or '')
    return p.scheme == 'https' and bool(p.hostname) and not p.username and not p.password


def parse_feed(content, source):
    root = ET.fromstring(content)
    records = []
    for item in root.iter():
        if tagname(item) not in ('item', 'entry'):
            continue
        title = child_text(item, ('title',))
        link = child_text(item, ('link',))
        if not link:
            for el in item:
                if tagname(el) == 'link' and el.attrib.get('href') and el.attrib.get('rel', 'alternate') == 'alternate':
                    link = el.attrib['href']
                    break
        if not title or not safe_https(link):
            continue
        summary = child_text(item, ('summary', 'description', 'content', 'encoded'))
        summary = re.sub(r'<[^>]*>', ' ', summary)
        summary = re.sub(r'\s+', ' ', summary).strip()[:4000]
        published = child_text(item, ('published', 'updated', 'pubDate', 'date'))
        records.append({
            'title': title[:500], 'agency': source['agency'][:200],
            'url': link[:2000], 'publishedAt': published[:80],
            'summary': summary, 'type': source.get('type', '연구·정책 자료'),
            'domains': source.get('domains', [])[:10],
            'keywords': source.get('keywords', [])[:30],
        })
    return records


def krit_identity(record):
    """Return a stable KRIT identity only for a recognized KRIT URL."""
    url = str(record.get('url') or record.get('originalDetailUrl') or '')
    parsed = urlparse(url)
    if parsed.hostname not in KRIT_HOSTS:
        return None
    match = re.search(r'/([a-z]+)_(?:view|list)\.do$', parsed.path, re.I)
    board = str(record.get('board') or (match.group(1) if match else '')).lower()
    source_id = str(record.get('sourceId') or parse_qs(parsed.query).get('nttId', [''])[0])
    if board in BOARDS and source_id.isdigit():
        return f'krit:{board}:{source_id}'
    return None


def identity(record):
    return krit_identity(record) or 'url:' + str(record['url']).lower()


def normalize_krit(record):
    """Use the public board list, not an unverified detail deep link."""
    result = dict(record)
    key = krit_identity(result)
    if not key:
        return result
    board = key.split(':')[1]
    original = result.get('originalDetailUrl')
    current = result.get('url', '')
    if not original and '_view.do' in current:
        original = current
    if original:
        result['originalDetailUrl'] = original
    result['url'] = f'https://www.krit.re.kr/krit/bbs/{board}_list.do'
    result['board'] = board
    result['sourceId'] = key.split(':')[2]
    result['urlStatus'] = 'unverified'
    return result


def merge_record(merged, record, *, latest=False):
    if not isinstance(record, dict) or not safe_https(record.get('url')):
        return
    record = normalize_krit(record)
    key = identity(record)
    previous = merged.get(key)
    if previous is None:
        merged[key] = record
        return
    if latest:
        combined = {**previous, **record}
        if not record.get('summary') and previous.get('summary'):
            combined['summary'] = previous['summary']
    else:
        combined = {**record, **previous}
        if not previous.get('summary') and record.get('summary'):
            combined['summary'] = record['summary']
    # Never let historical detail URLs overwrite the safe board URL.
    merged[key] = normalize_krit(combined)


def main():
    conf = json.loads(CONFIG.read_text(encoding='utf-8'))
    sources = conf.get('sources', [])
    if not isinstance(sources, list):
        raise ValueError('sources must be an array')

    merged = {}
    if OUTPUT.exists():
        try:
            for record in json.loads(OUTPUT.read_text(encoding='utf-8')).get('items', []):
                merge_record(merged, record)
        except (ValueError, KeyError, TypeError) as exc:
            print(f'Existing feed warning: {exc}', file=sys.stderr)

    # Latest KRIT snapshot wins over historical research entries.
    krit_loaded = False
    if KRIT_FILE.exists():
        try:
            krit = json.loads(KRIT_FILE.read_text(encoding='utf-8'))
            for record in krit.get('items', []):
                merge_record(merged, record, latest=True)
            krit_loaded = bool(krit.get('items'))
        except (ValueError, TypeError, KeyError) as exc:
            print(f'KRIT merge warning: {exc}', file=sys.stderr)

    failures = []
    successes = 0
    for src in sources:
        url = src.get('url', '')
        if not safe_https(url) or not src.get('agency'):
            failures.append('Invalid source configuration: HTTPS URL and agency required')
            continue
        try:
            req = Request(url, headers={
                'User-Agent': 'NJ-STRATEGY-HUB-ResearchFeed/1.0',
                'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/xml',
            })
            with urlopen(req, timeout=18) as response:
                if not safe_https(response.geturl()):
                    raise ValueError('Insecure redirect')
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('Feed size limit exceeded')
            parsed = parse_feed(raw, src)
            for record in parsed:
                merge_record(merged, record, latest=True)
            successes += 1
            print(f"{src['agency']}: {len(parsed)} entries")
        except Exception as exc:
            failures.append(f"{src.get('agency', 'unknown')}: {type(exc).__name__}: {exc}")

    if sources and successes == 0 and not krit_loaded:
        print('All sources failed; keeping existing research.json', file=sys.stderr)
        for msg in failures:
            print(msg, file=sys.stderr)
        return 1

    records = sorted(merged.values(), key=lambda x: (
        x.get('publishedAt', ''), x.get('title', '')
    ), reverse=True)[:MAX_ITEMS]
    data = {
        'schema': 'nj-research-feed-v1',
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'source': 'Configured public RSS/Atom feeds',
        'configuredSources': len(sources), 'successfulSources': successes,
        'warnings': failures, 'items': records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Published {len(records)} research records; {len(failures)} warnings')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Collect public KRIT board metadata, retaining historical records.

Detailed URLs use the official board navigation query shape. They are not
claimed to be independently verified unless HTTP validation succeeds.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/krit.json'
BASE = 'https://www.krit.re.kr/krit/bbs/'
BOARDS = {
    'notice': ('공지사항', '사업공고·공지', '05010000'),
    'regulatory': ('규정자료', '규정·지침', None),
    'press': ('보도자료', '정책·기술 동향', None),
}
PAGES = 3
MAX_BYTES = 3_000_000
PAT = re.compile(r"fnView\(\s*'([a-z]+)'\s*,\s*'([^']*)'\s*,\s*'(\d+)'", re.I)


def fetch(url):
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NJ-STRATEGY-HUB/1.1; public metadata)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urlopen(req, timeout=20) as resp:
        final = resp.geturl()
        parsed = urlparse(final)
        if parsed.hostname not in ('www.krit.re.kr', 'krit.re.kr') or parsed.scheme != 'https':
            raise ValueError('Unexpected redirect')
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('HTML size limit exceeded')
        return raw.decode('utf-8', 'replace')


def detail_url(board, ntt, page=1, menu_no=None):
    # Preserve the navigation parameter structure observed in the official KRIT UI.
    # An empty searchWrd is NOT proof that the URL is reachable.
    params = [
        ('bbsId', board), ('article_category', ''), ('nttId', ntt),
        ('page', str(page)), ('searchCnd', '0'), ('searchWrd', ''),
        ('startd', ''), ('endd', ''), ('csrf', ''),
    ]
    if menu_no:
        params.append(('menu_no', menu_no))
    return f'{BASE}{board}_view.do?{urlencode(params)}'


def parse_list(html, board, page=1):
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    menu_no = BOARDS[board][2]
    for li in soup.select('ul.listType > li'):
        a = li.find('a', onclick=True)
        if not a:
            continue
        match = PAT.search(a.get('onclick', ''))
        if not match or match.group(1).lower() != board:
            continue
        title = re.sub(r'^\s*(?:공지|\d+)\s+', '', a.get_text(' ', strip=True)).strip()
        if not title:
            continue
        date = li.select_one('li.date')
        published = date.get_text(' ', strip=True) if date else ''
        ntt = match.group(3)
        result.append({
            'title': title[:500],
            'agency': '국방기술진흥연구소',
            'url': detail_url(board, ntt, page, menu_no),
            'publishedAt': published,
            'summary': '',
            'type': BOARDS[board][1],
            'domains': ['국방·방산'],
            'keywords': [BOARDS[board][0]],
            'board': board,
            'sourceId': ntt,
            'hasAttachment': bool(li.select_one('.file')),
            'urlStatus': 'unverified',
        })
    return result


def identity(record):
    board = str(record.get('board') or '').lower()
    source_id = str(record.get('sourceId') or '')
    if not board or not source_id:
        parsed = urlparse(record.get('url', ''))
        match = re.search(r'/([a-z]+)_view\.do$', parsed.path, re.I)
        if match:
            board = board or match.group(1).lower()
        source_id = source_id or parse_qs(parsed.query).get('nttId', [''])[0]
    if board in BOARDS and source_id.isdigit():
        return f'{board}:{source_id}', board, source_id
    return 'url:' + str(record.get('url', '')).lower(), None, None


def normalize_old(record):
    key, board, ntt = identity(record)
    if board and ntt:
        record['board'] = board
        record['sourceId'] = ntt
        record['url'] = detail_url(board, ntt, 1, BOARDS[board][2])
        record['urlStatus'] = 'unverified'
    return key, record


def main():
    merged = {}
    if OUTPUT.exists():
        try:
            for record in json.loads(OUTPUT.read_text(encoding='utf-8')).get('items', []):
                if isinstance(record, dict) and record.get('url'):
                    key, record = normalize_old(record)
                    merged[key] = record
        except (ValueError, TypeError) as exc:
            print(f'WARNING: old JSON could not be loaded: {exc}', file=sys.stderr)
    warnings = []
    board_counts = {}
    success = 0
    for board in BOARDS:
        count = 0
        for page in range(1, PAGES + 1):
            url = f'{BASE}{board}_list.do?{urlencode({"page": page})}'
            try:
                records = parse_list(fetch(url), board, page)
                if not records:
                    warnings.append(f'{board} page {page}: no records parsed; verify page structure')
                    break
                for record in records:
                    key, _, _ = identity(record)
                    previous = merged.get(key, {})
                    for field in ('summary',):
                        if previous.get(field) and not record.get(field):
                            record[field] = previous[field]
                    merged[key] = record
                count += len(records)
                if page < PAGES:
                    time.sleep(0.5)
            except Exception as exc:
                warnings.append(f'{board} page {page}: {type(exc).__name__}: {exc}')
                break
        board_counts[board] = count
        if count:
            success += 1
    if success == 0:
        print('No KRIT boards parsed; existing output left unchanged', file=sys.stderr)
        for warning in warnings:
            print(warning, file=sys.stderr)
        return 1
    data = {
        'schema': 'nj-krit-feed-v1',
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'agency': '국방기술진흥연구소',
        'successfulBoards': success,
        'boardCounts': board_counts,
        'warnings': warnings,
        'items': sorted(merged.values(), key=lambda r: (r.get('publishedAt', ''), r.get('title', '')), reverse=True)[:5000],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'KRIT boards {success}/3, records {len(data["items"])}; warnings {len(warnings)}')
    for warning in warnings:
        print('WARNING:', warning)
    return 0


if __name__ == '__main__':
    sys.exit(main())

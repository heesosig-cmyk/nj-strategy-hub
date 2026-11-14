
#!/usr/bin/env python3
"""Collect KRIT public board metadata using the site's GET navigation form.

Generated detail URLs remain unverified until tested against the live site.
"""
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/krit.json'
BASE = 'https://www.krit.re.kr/krit/bbs/'
BOARDS = {
    'notice': ('공지사항', '사업공고·공지'),
    'regulatory': ('규정자료', '규정·지침'),
    'press': ('보도자료', '정책·기술 동향'),
}
PAGES = 3
MAX_BYTES = 3_000_000

# fnView(bbsId, category, articleId, page, searchCnd, searchWrd)
PAT = re.compile(
    r"fnView\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'(\d+)'\s*,"
    r"\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*\)", re.I
)


def fetch(url):
    req = Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (compatible; NJ-STRATEGY-HUB/1.2; public metadata)',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urlopen(req, timeout=20) as resp:
        final = urlparse(resp.geturl())
        if final.scheme != 'https' or final.hostname not in (
            'www.krit.re.kr', 'krit.re.kr'
        ):
            raise ValueError('Unexpected redirect')
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('HTML size limit exceeded')
        return raw.decode('utf-8', 'replace')


def form_fields(soup):
    """Read the GET form fields in their original HTML order."""
    form = soup.select_one('form#form')
    if form is None or (form.get('method') or 'get').lower() != 'get':
        return None

    fields = []
    for control in form.select('input[name]'):
        if control.get('disabled') is not None:
            continue
        fields.append((control['name'], control.get('value', '')))

    required = {'bbsId', 'nttId', 'page', 'searchCnd', 'searchWrd'}
    if not required.issubset({name for name, _ in fields}):
        return None
    return fields


def detail_url(board, ntt, args, fields):
    """Reconstruct the GET URL using the observed fnView assignments."""
    bbs_id, category, article_id, page, search_cnd, search_wrd = args

    if bbs_id.lower() != board or article_id != ntt:
        raise ValueError('fnView board/id mismatch')

    replacements = {
        'bbsId': bbs_id,
        'nttId': article_id,
        'page': page,
        'searchCnd': search_cnd,
        'searchWrd': search_wrd,
    }

    # The website's fnView does not update article_category.
    params = [
        (name, replacements.get(name, value))
        for name, value in fields
    ]
    return f'{BASE}{board}_view.do?{urlencode(params)}'


def parse_list(html, board):
    soup = BeautifulSoup(html, 'html.parser')
    fields = form_fields(soup)

    if fields is None:
        raise ValueError('KRIT GET navigation form missing or changed')

    records = []
    for li in soup.select('ul.listType > li'):
        a = li.find('a', onclick=True)
        if not a:
            continue

        match = PAT.search(a.get('onclick', ''))
        if not match or match.group(1).lower() != board:
            continue

        args = match.groups()
        ntt = args[2]

        title = re.sub(
            r'^\s*(?:공지|\d+)\s+',
            '',
            a.get_text(' ', strip=True)
        ).strip()
        if not title:
            continue

        date = li.select_one('li.date')

        records.append({
            'title': title[:500],
            'agency': '국방기술진흥연구소',
            'url': detail_url(board, ntt, args, fields),
            'publishedAt': date.get_text(' ', strip=True) if date else '',
            'summary': '',
            'type': BOARDS[board][1],
            'domains': ['국방·방산'],
            'keywords': [BOARDS[board][0]],
            'board': board,
            'sourceId': ntt,
            'hasAttachment': bool(li.select_one('.file')),
            'urlStatus': 'unverified',
        })

    return records


def identity(record):
    board = str(record.get('board') or '').lower()
    source_id = str(record.get('sourceId') or '')
    parsed = urlparse(str(record.get('url') or ''))

    if not board:
        match = re.search(
            r'/([a-z]+)_view\.do$', parsed.path, re.I
        )
        if match:
            board = match.group(1).lower()

    if not source_id:
        source_id = parse_qs(parsed.query).get('nttId', [''])[0]

    if board in BOARDS and source_id.isdigit():
        return f'{board}:{source_id}'

    return 'url:' + str(record.get('url') or '').lower()


def main():
    merged = {}

    if OUTPUT.exists():
        try:
            old_items = json.loads(
                OUTPUT.read_text(encoding='utf-8')
            ).get('items', [])

            for record in old_items:
                if isinstance(record, dict) and record.get('url'):
                    record['urlStatus'] = 'unverified'
                    merged[identity(record)] = record

        except (ValueError, TypeError) as exc:
            print(
                f'WARNING: existing JSON unreadable: {exc}',
                file=sys.stderr
            )

    warnings = []
    counts = {}
    success = 0

    for board in BOARDS:
        count = 0

        for page in range(1, PAGES + 1):
            url = (
                f'{BASE}{board}_list.do?'
                f'{urlencode({"page": page})}'
            )

            try:
                records = parse_list(fetch(url), board)

                if not records:
                    warnings.append(
                        f'{board} page {page}: no records parsed'
                    )
                    break

                for record in records:
                    key = identity(record)
                    previous = merged.get(key, {})

                    if previous.get('summary'):
                        record['summary'] = previous['summary']

                    merged[key] = record

                count += len(records)

                if page < PAGES:
                    time.sleep(0.5)

            except Exception as exc:
                warnings.append(
                    f'{board} page {page}: '
                    f'{type(exc).__name__}: {exc}'
                )
                break

        counts[board] = count
        if count:
            success += 1

    if success == 0:
        print(
            'No KRIT boards parsed; existing output unchanged',
            file=sys.stderr
        )
        for warning in warnings:
            print('WARNING:', warning, file=sys.stderr)
        return 1

    data = {
        'schema': 'nj-krit-feed-v1',
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'agency': '국방기술진흥연구소',
        'successfulBoards': success,
        'boardCounts': counts,
        'warnings': warnings,
        'items': sorted(
            merged.values(),
            key=lambda r: (
                r.get('publishedAt', ''),
                r.get('title', '')
            ),
            reverse=True
        )[:5000],
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8'
    )

    print(
        f'KRIT boards {success}/3, '
        f'records {len(data["items"])}; '
        f'warnings {len(warnings)}'
    )

    for warning in warnings:
        print('WARNING:', warning)

    return 0


if __name__ == '__main__':
    sys.exit(main())

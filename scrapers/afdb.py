import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

from utils import matches_target_country

logger = logging.getLogger(__name__)

BASE_URL = 'https://www.afdb.org'
LIST_URL = urljoin(BASE_URL, '/en/projects-and-operations/procurement/notices')


def _parse_date(date_str):
    if not date_str:
        return None, ''
    date_str = date_str.strip()
    for fmt in ('%d-%b-%Y', '%d %B %Y', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.replace(tzinfo=timezone.utc), dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    return None, date_str


def _parse_notice_id(ref, title):
    nid = ref.strip() if ref else ''
    if not nid:
        nid = title.strip()[:30] if title else ''
    clean = re.sub(r'[^a-zA-Z0-9_-]', '-', nid).strip('-')
    return f'AFDB-{clean}' if clean else None


def scrape_afdb(browser=None, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    scraper = cloudscraper.create_scraper()
    results = []

    if progress_cb:
        progress_cb('starting', 0, 'Connecting to AfDB procurement notices...')

    try:
        logger.info(f'[AFDB] Fetching {LIST_URL}...')
        resp = scraper.get(LIST_URL, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f'[AFDB] Failed to fetch notices page: {e}')
        if progress_cb:
            progress_cb('error', 0, f'Connection failed: {e}')
        return []

    soup = BeautifulSoup(resp.text, 'html.parser')
    table = soup.select_one('table')
    if not table:
        logger.info('[AFDB] No table found on notices page')
        if progress_cb:
            progress_cb('done', 100, 'No notices table found')
        return []

    rows = table.select('tr')[1:]  # skip header
    logger.info(f'[AFDB] Found {len(rows)} rows in table')

    if progress_cb:
        progress_cb('parsing', 40, f'Parsing {len(rows)} notices...')

    for row in rows:
        cells = row.find_all('td')
        if len(cells) < 5:
            continue

        ref = cells[0].get_text(strip=True)
        title = cells[1].get_text(strip=True)
        country = cells[2].get_text(strip=True)
        status = cells[3].get_text(strip=True)
        approval = cells[4].get_text(strip=True)

        if not matches_target_country(country):
            continue

        link = cells[1].find('a')
        url = urljoin(BASE_URL, link['href']) if link and link.get('href') else ''

        notice_id = _parse_notice_id(ref, title)
        if not notice_id or notice_id in seen_set:
            continue

        published_dt, published_str = _parse_date(approval)

        results.append({
            'noticeId': notice_id,
            'title': title,
            'organization': 'African Development Bank',
            'country': country,
            'deadline': '',
            'deadline_date': None,
            'reference': ref,
            'published': published_str or approval,
            'published_date': published_dt.isoformat() if published_dt else None,
            'description': f'AfDB project: {title} ({status})',
            'url': url,
            'source': 'AFDB',
        })

    logger.info(f'[AFDB] Done — collected {len(results)} new NG/LR notices')
    if progress_cb:
        progress_cb('done', 100, f'Fetched {len(results)} new notices')

    return results

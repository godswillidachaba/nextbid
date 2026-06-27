import logging
import re
from datetime import datetime

from utils import matches_target_country

logger = logging.getLogger(__name__)


def _parse_date_to_iso(s):
    if not s or s.strip().lower() in ('nv', 'n/a', ''):
        return None
    s = s.strip()
    for fmt in ('%d.%m.%Y', '%d-%b-%Y', '%d %B %Y', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%Y-%m-%dT00:00:00Z')
        except ValueError:
            continue
    return None


def extract_country_from_title(title):
    if not title:
        return ''
    known = [
        'nigeria', 'liberia', 'ghana', 'kenya', 'ethiopia', 'tanzania',
        'south africa', 'rwanda', 'uganda', 'mozambique', 'angola',
        'congo', 'dr congo', 'cameroon', "côte d'ivoire", 'senegal',
        'mali', 'burkina faso', 'niger', 'chad', 'sudan', 'south sudan',
        'somalia', 'zimbabwe', 'zambia', 'malawi', 'botswana', 'namibia',
        'india', 'bangladesh', 'pakistan', 'afghanistan', 'indonesia',
        'philippines', 'vietnam', 'cambodia', 'myanmar', 'laos',
        'ukraine', 'jordan', 'lebanon', 'yemen', 'iraq', 'syria',
        'colombia', 'peru', 'brazil', 'mexico', 'haiti',
        'morocco', 'algeria', 'tunisia', 'egypt', 'libya',
    ]
    lower = title.lower()
    for country in known:
        if country in lower:
            return ' '.join(w.capitalize() for w in country.split())
    m = re.search(r'\bfor\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b', title)
    return m.group(1) if m else ''


def scrape_giz(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 5, 'Loading GIZ procurement notices...')

        logger.info('[GIZ] Navigating to procurement notices...')
        page.goto(
            'https://ausschreibungen.giz.de/Satellite/company/welcome.do?method=showTable',
            wait_until='domcontentloaded',
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        if progress_cb:
            progress_cb('parsing', 10, 'Extracting notices...')

        rows = page.evaluate("""() => {
            const tables = document.querySelectorAll('table');
            let targetTable = null;
            for (const t of tables) {
                const rows = t.querySelectorAll('tr');
                if (rows.length > 3) {
                    targetTable = t;
                    break;
                }
            }
            if (!targetTable) return [];

            const trs = targetTable.querySelectorAll('tr');
            const result = [];
            for (const tr of trs) {
                const cells = tr.querySelectorAll('td');
                if (cells.length < 5) continue;

                const pidLink = cells[5]?.querySelector('a');
                const pidHref = pidLink ? pidLink.href : '';
                const pidMatch = pidHref.match(/pid=(\\d+)/);

                result.push({
                    noticeId: pidMatch ? pidMatch[1] : pidHref,
                    title: cells[2]?.innerText?.trim() || '',
                    organization: cells[4]?.innerText?.trim() || 'GIZ',
                    country: '',
                    deadline: cells[1]?.innerText?.trim() || '',
                    reference: '',
                    published: cells[0]?.innerText?.trim() || '',
                    url: pidHref || '',
                });
            }
            return result;
        }""")

        logger.info(f'[GIZ] Found {len(rows)} raw rows')

        for item in rows:
            nid = item.get('noticeId')
            if not nid or nid in seen_set:
                continue
            if nid not in collected:
                collected[nid] = item

        result = list(collected.values())

        if progress_cb:
            progress_cb('processing', 80, f'Processing {len(result)} notices...')

        for item in result:
            item['country'] = extract_country_from_title(item['title'])
            item['description'] = ''
            item['published_date'] = _parse_date_to_iso(item.get('published'))
            item['deadline_date'] = _parse_date_to_iso(item.get('deadline'))

        result = [item for item in result if matches_target_country(item['country'])]

        logger.info(f'[GIZ] Done — collected {len(result)} new notices')

        if progress_cb:
            progress_cb('done', 100, f'Found {len(result)} new notices')

        return result

    finally:
        page.close()

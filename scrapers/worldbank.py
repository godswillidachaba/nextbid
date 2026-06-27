import logging
from datetime import datetime

from utils import matches_target_country

logger = logging.getLogger(__name__)


def scrape_worldbank(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 5, 'Loading World Bank opportunities...')

        logger.info('[WorldBank] Navigating to business opportunities page...')
        page.goto(
            'https://projects.worldbank.org/en/projects-operations/opportunities?srce=both',
            wait_until='domcontentloaded',
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        max_pages = 10

        for page_num in range(1, max_pages + 1):
            if page_num > 1:
                clicked = page.evaluate("""(p) => {
                    const links = document.querySelectorAll('ul.pagination a');
                    for (const a of links) {
                        if (a.innerText.trim() === String(p)) {
                            a.click();
                            return true;
                        }
                    }
                    return false;
                }""", page_num)
                if not clicked:
                    logger.info(f'[WorldBank] Page {page_num} link not found, stopping')
                    break
                page.wait_for_timeout(5000)

            if progress_cb:
                pct = 10 + int((page_num / max_pages) * 60)
                progress_cb(
                    'parsing', pct,
                    f'Scraping page {page_num}/{max_pages}...'
                )

            rows = page.evaluate("""() => {
                const links = document.querySelectorAll('table a[href*="/procurement-detail/"]');
                return Array.from(links).map(a => {
                    const tr = a.closest('tr');
                    if (!tr) return null;
                    const cells = tr.querySelectorAll('td');
                    return {
                        noticeId: a.href.split('/').pop() || a.href,
                        title: a.innerText?.trim() || '',
                        organization: 'World Bank',
                        country: cells[1]?.innerText?.trim() || '',
                        deadline: cells[7]?.innerText?.trim() || '',
                        reference: '',
                        published: cells[6]?.innerText?.trim() || '',
                        url: a.href,
                    };
                }).filter(Boolean);
            }""")

            logger.info(f'[WorldBank] Page {page_num}: found {len(rows)} rows')

            for item in rows:
                nid = item.get('noticeId')
                country = item.get('country', '')
                if not nid or nid in seen_set:
                    continue
                if not matches_target_country(country):
                    continue
                if nid not in collected:
                    collected[nid] = item

        logger.info(f'[WorldBank] Total collected (NG/LR only): {len(collected)}')

        result = list(collected.values())

        if progress_cb:
            progress_cb('processing', 80, f'Processing {len(result)} notices...')

        for item in result:
            item['description'] = ''
            published = item.get('published', '')
            if published:
                try:
                    dt = datetime.strptime(published, '%B %d, %Y')
                    item['published_date'] = dt.strftime('%Y-%m-%dT00:00:00Z')
                except (ValueError, TypeError):
                    item['published_date'] = None
            else:
                item['published_date'] = None
            deadline = item.get('deadline', '')
            if deadline:
                try:
                    dt = datetime.strptime(deadline, '%B %d, %Y')
                    item['deadline_date'] = dt.strftime('%Y-%m-%dT00:00:00Z')
                except (ValueError, TypeError):
                    item['deadline_date'] = None
            else:
                item['deadline_date'] = None

        logger.info(f'[WorldBank] Done — collected {len(result)} new NG/LR notices')

        if progress_cb:
            progress_cb('done', 100, f'Found {len(result)} new notices')

        return result

    finally:
        page.close()

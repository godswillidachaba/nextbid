import logging
import re
from datetime import datetime

from utils import matches_target_country

logger = logging.getLogger(__name__)

CRS_URL = 'https://www.crs.org/bid-opportunities'


def _parse_date(text):
    if not text:
        return None, None
    text = text.strip()

    deadline = None
    published = None

    m = re.search(r'(?:Closing Date|Deadline)\s*:\s*(.+?)(?:\s*EST|\s*$)', text, re.IGNORECASE)
    if m:
        dt = _parse_single_date(m.group(1).strip())
        if dt:
            deadline = dt

    m = re.search(r'(?:Publication Date/Time|Issue Date|Published)\s*:\s*(.+?)(?:\s*EST|\s*$)', text, re.IGNORECASE)
    if m:
        dt = _parse_single_date(m.group(1).strip())
        if dt:
            published = dt

    return deadline, published


def _parse_single_date(s):
    if not s:
        return None
    s = s.strip().rstrip(',').strip()
    fmts = [
        '%A, %B %d, %Y',
        '%B %d, %Y',
        '%A, %d %B %Y',
        '%d %B %Y',
        '%Y-%m-%d',
    ]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime('%Y-%m-%dT00:00:00Z')
        except ValueError:
            continue
    return None


def scrape_crs(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 5, 'Loading CRS Bid Opportunities...')

        logger.info('[CRS] Navigating to Bid Opportunities page...')
        page.goto(CRS_URL, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(3000)

        for _ in range(8):
            page.evaluate("window.scrollBy(0, 300)")
            page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        current_url = page.url
        logger.info(f'[CRS] Current URL after navigation: {current_url}')

        if 'crs.org' not in current_url.lower():
            logger.warning(f'[CRS] Redirected away from CRS to {current_url}, aborting')
            if progress_cb:
                progress_cb('done', 100, 'CRS page redirected — no results')
            return []

        if progress_cb:
            progress_cb('parsing', 20, 'Parsing bid listings...')

        items = page.evaluate("""() => {
            const results = [];

            const cards = document.querySelectorAll('.crs-card__info');
            if (cards.length > 0) {
                cards.forEach(card => {
                    const h3 = card.querySelector('h3');
                    const link = card.querySelector('a');
                    const fullText = card.innerText || '';
                    results.push({
                        title: h3 ? h3.innerText.trim() : '',
                        url: link ? link.href : '',
                        fullText: fullText,
                    });
                });
                return results;
            }

            const headings = document.querySelectorAll('h2, h3, h4');
            const pageUrl = window.location.href;
            headings.forEach(h => {
                const text = h.innerText.trim();
                if (text.length < 5 || text.length > 200) return;
                const container = h.closest('div, section, article, li') || h.parentElement;
                const allText = container ? container.innerText : '';
                if (!allText) return;
                const headingLink = h.querySelector('a');
                const url = headingLink ? headingLink.href : '';
                if (!url || url === pageUrl) return;
                results.push({
                    title: text,
                    fullText: allText,
                    url: url,
                });
            });

            return results;
        }""")

        logger.info(f'[CRS] Found {len(items)} potential items on page')

        for item in items:
            full_text = item.get('fullText', '') or ''
            title = item.get('title', '') or ''
            url = item.get('url', '') or CRS_URL

            deadline, published = _parse_date(full_text)

            ref = item.get('bidNo', '') or ''
            if not ref:
                m = re.search(r'(?:Bid No\.?|RFP[\.\s]*No|RFQ[\.\s]*No|Reference)\s*:?\s*(\S[\w\-\.]+)', full_text, re.IGNORECASE)
                if m:
                    ref = m.group(1).strip()

            status = item.get('status', '') or ''
            if not status:
                m = re.search(r'Status\s*:?\s*(\w+)', full_text, re.IGNORECASE)
                if m:
                    status = m.group(1).strip()

            country = item.get('country', '') or ''
            if not country:
                m = re.search(r'(?:Country|Location)\s*:?\s*(.+?)(?:\n|$)', full_text, re.IGNORECASE)
                if m:
                    country = m.group(1).strip()
            if not country:
                desc_match = re.search(r'Description\s*:?\s*(.+?)(?:\n|$)', full_text, re.IGNORECASE)
                if desc_match:
                    country = desc_match.group(1).strip()

            organization = 'Catholic Relief Services'

            desc_text = full_text[:500] if full_text else ''

            nid = ref or url.split('/')[-1] or title[:50]
            nid = f'CRS-{nid}'

            if nid in seen_set:
                continue

            if not matches_target_country(full_text + ' ' + title + ' ' + country):
                continue

            if nid not in collected:
                collected[nid] = {
                    'noticeId': nid,
                    'title': title,
                    'organization': organization,
                    'country': country,
                    'deadline': '',
                    'reference': ref,
                    'published': '',
                    'url': url,
                    'deadline_date': deadline,
                    'published_date': published,
                    'description': desc_text,
                    'status': status,
                }

        logger.info(f'[CRS] Total collected (NG/LR only): {len(collected)}')

        result = list(collected.values())

        if progress_cb:
            progress_cb('processing', 80, f'Processing {len(result)} notices...')

        for item in result:
            if not item.get('published_date'):
                item['published_date'] = None
            if not item.get('deadline_date'):
                item['deadline_date'] = None

        logger.info(f'[CRS] Done — collected {len(result)} new NG/LR notices')

        if progress_cb:
            progress_cb('done', 100, f'Found {len(result)} new notices')

        return result

    finally:
        page.close()

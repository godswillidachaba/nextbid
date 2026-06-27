import logging
import re
from datetime import datetime

from utils import matches_target_country

logger = logging.getLogger(__name__)

PROCUREMENT_KEYWORDS = re.compile(
    r'(tender|expression.?of.?interest|eoi|procurement|call.?for.?proposal|'
    r'supply.?and.?delivery|competitive.?bidding|rfp|request.?for.?proposal|'
    r'vendor|prequalif|pre.?qualif|quotation|notice.?inviting|'
    r'terms.?of.?reference|consultanc|request.?for.?quotation|'
    r'invit|solicit|offer|grant|opportunity|call.?for|bid)',
    re.IGNORECASE,
)

COUNTRY_PAGES = [
    {
        'country': 'Nigeria',
        'url': 'https://nigeria.actionaid.org/jobs',
        'label': 'Nigeria Jobs',
    },
    {
        'country': 'Nigeria',
        'url': 'https://nigeria.actionaid.org/publications',
        'label': 'Nigeria Publications',
    },
    {
        'country': 'Liberia',
        'url': 'https://liberia.actionaid.org/publications',
        'label': 'Liberia Publications',
    },
]


def _parse_date(s):
    if not s:
        return None
    try:
        dt = datetime.strptime(s.strip(), '%d %B %Y')
        return dt.strftime('%Y-%m-%dT00:00:00Z')
    except ValueError:
        pass
    try:
        dt = datetime.strptime(s.strip(), '%B %d, %Y')
        return dt.strftime('%Y-%m-%dT00:00:00Z')
    except ValueError:
        pass
    return None


def _is_procurement_item(title, body_text):
    text = f'{title} {body_text}'
    return bool(PROCUREMENT_KEYWORDS.search(text))


def _scrape_page(browser, page_config, seen_set, collected):
    country = page_config['country']
    url = page_config['url']
    label = page_config['label']

    page = browser.new_page()
    try:
        logger.info(f'[ActionAid] Navigating to {label}...')
        page.goto(url, wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(5000)

        try:
            btn = page.query_selector('button:has-text("Accept all cookies")')
            if btn:
                btn.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        page.wait_for_timeout(3000)

        items = page.evaluate("""() => {
            const base = window.location.origin;
            const articles = document.querySelectorAll('.standard-listing--item.views-row, .views-row');
            return Array.from(articles).map(el => {
                const titleEl = el.querySelector('.search-result--title a, h4 a, h2 a, h3 a, .node-title a');
                const bodyEl = el.querySelector('.search-result--summary, .node__content, .field-content');
                const link = titleEl || el.querySelector('a');
                return {
                    title: titleEl ? titleEl.innerText.trim() : (link ? link.innerText.trim() : ''),
                    href: link ? (link.getAttribute('href') || '').startsWith('/')
                        ? base + link.getAttribute('href')
                        : link.href : '',
                    date: '',
                    body: bodyEl ? bodyEl.innerText.trim().substring(0, 500) : '',
                    text: el.innerText.trim(),
                };
            });
        }""")

        logger.info(f'[ActionAid] {label}: found {len(items)} items')

        for item in items:
            title = item.get('title', '')
            if not title:
                continue

            if not _is_procurement_item(title, item.get('text', '')):
                continue

            nid = item.get('href', title)
            if nid in seen_set:
                continue
            if nid in collected:
                continue

            collected[nid] = {
                'noticeId': nid,
                'title': title,
                'organization': 'ActionAid',
                'country': country,
                'deadline': '',
                'reference': '',
                'published': item.get('date', ''),
                'url': item.get('href', ''),
                'description': item.get('body', ''),
                'source_country': country,
                'source_label': label,
            }

        logger.info(f'[ActionAid] {label}: collected {sum(1 for v in collected.values() if v["source_label"] == label)} new procurement items')

    finally:
        page.close()


def scrape_actionaid(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    collected = {}
    total_pages = len(COUNTRY_PAGES)

    try:
        for idx, page_config in enumerate(COUNTRY_PAGES):
            if progress_cb:
                pct = int((idx / total_pages) * 70)
                progress_cb(
                    'navigating', max(pct, 5),
                    f'Scraping {page_config["label"]}...'
                )

            _scrape_page(browser, page_config, seen_set, collected)

        result = list(collected.values())

        logger.info(f'[ActionAid] Filtering {len(result)} items by target country...')

        filtered = []
        for item in result:
            country = item.get('country', '')
            if not matches_target_country(country):
                title = item.get('title', '')
                body = item.get('description', '')
                if not matches_target_country(f'{title} {body}'):
                    logger.info(
                        f'[ActionAid] Skipping (not NG/LR): {item.get("title", "")} '
                        f'[country={country}]'
                    )
                    continue
            filtered.append(item)

        logger.info(f'[ActionAid] After country filter: {len(filtered)} items')

        if progress_cb:
            progress_cb('processing', 80, f'Processing {len(filtered)} notices...')

        for item in filtered:
            item['description'] = item.get('description', '')
            pub = item.get('published', '')
            item['published_date'] = _parse_date(pub)
            item['deadline_date'] = None
            item['noticeId'] = item.get('noticeId', item.get('url', ''))

        if progress_cb:
            progress_cb('done', 100, f'Found {len(filtered)} new notice(s)')

        logger.info(f'[ActionAid] Done — collected {len(filtered)} new NG/LR procurement notices')
        return filtered

    except Exception as e:
        logger.exception(f'[ActionAid] Scrape failed: {e}')
        if progress_cb:
            progress_cb('error', 0, f'Error: {e}')
        return []

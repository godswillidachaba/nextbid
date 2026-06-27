import logging
import re
from datetime import datetime

from utils import matches_target_country

logger = logging.getLogger(__name__)

FCDO_KEYWORDS = [
    'Foreign, Commonwealth and Development Office',
    'Foreign Commonwealth and Development Office',
    'Foreign Commonwealth Development Office',
    'FCDO',
    'FCDO Services',
]
MAX_PAGES = 5


def _parse_date_to_iso(s):
    if not s:
        return None
    cleaned = re.sub(r'\s+', ' ', s.strip())
    for fmt in ('%d %B %Y, %I:%M %p', '%d %B %Y, %H:%M', '%d %B %Y', '%d-%b-%Y'):
        try:
            text = cleaned
            if '%p' in fmt and 'm' in text[-4:].lower():
                text = text[:-2] + ' ' + text[-2:].upper()
            dt = datetime.strptime(text, fmt)
            return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            continue
    return None


def _is_fcdo_org(name):
    if not name:
        return False
    n = name.lower()
    return any(k.lower() in n for k in FCDO_KEYWORDS)


def scrape_fcdo(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 5, 'Loading Find a Tender...')

        logger.info('[FCDO] Navigating to Find a Tender search...')
        page.goto(
            'https://www.find-tender.service.gov.uk/Search/Results',
            wait_until='domcontentloaded',
            timeout=60000,
        )

        page.wait_for_timeout(3000)

        cookie_btn = page.query_selector('#ft_accept_all_cookies')
        if cookie_btn:
            logger.info('[FCDO] Accepting cookies...')
            cookie_btn.click()
            page.wait_for_timeout(1000)

        keyword_input = page.query_selector('#keywords')
        if keyword_input:
            logger.info('[FCDO] Typing search keywords...')
            keyword_input.fill(
                '"Foreign Commonwealth and Development Office" OR "FCDO" OR "FCDO Services"'
            )
            page.wait_for_timeout(500)

            submit_btn = page.query_selector(
                'button[type="submit"], input[type="submit"], .search-submit-button'
            )
            if submit_btn:
                submit_btn.click()
            else:
                keyword_input.press('Enter')
            page.wait_for_timeout(5000)
        else:
            logger.info('[FCDO] No keyword input found, trying URL-based search...')
            page.goto(
                'https://www.find-tender.service.gov.uk/Search/Results?keywords=%22Foreign+Commonwealth+and+Development+Office%22&stage[2]=1',
                wait_until='domcontentloaded',
                timeout=60000,
            )
            page.wait_for_timeout(3000)

        if progress_cb:
            progress_cb('parsing', 20, 'Parsing search results...')

        for page_num in range(1, MAX_PAGES + 1):
            if page_num > 1:
                next_link = page.evaluate("""() => {
                    const links = document.querySelectorAll('a[href*="page="], a.govuk-link');
                    for (const a of links) {
                        if (a.textContent.trim() === 'Next' || a.getAttribute('aria-label') === 'Next page') {
                            return a.href;
                        }
                    }
                    return null;
                }""")
                if next_link:
                    logger.info(f'[FCDO] Going to page {page_num}...')
                    page.goto(next_link, wait_until='domcontentloaded', timeout=60000)
                    page.wait_for_timeout(3000)
                else:
                    logger.info(f'[FCDO] Page {page_num} not found, stopping')
                    break

            if progress_cb:
                pct = 20 + int((page_num / MAX_PAGES) * 50)
                progress_cb(
                    'parsing', pct,
                    f'Scraping page {page_num}/{MAX_PAGES}...'
                )

            rows = page.evaluate(r"""() => {
                const items = document.querySelectorAll('.search-result');
                return Array.from(items).map(item => {
                    const header = item.querySelector('.search-result-header');
                    const titleLink = header ? header.querySelector('a') : null;
                    const subHeader = item.querySelector('.search-result-sub-header');
                    const descEl = item.querySelector('[id$="-description"]');

                    const entries = item.querySelectorAll('.search-result-entry');
                    const meta = {};
                    entries.forEach(entry => {
                        const dt = entry.querySelector('dt');
                        const dd = entry.querySelector('dd');
                        if (dt && dd) {
                            const key = dt.textContent.replace(/[\s:]/g, ' ').trim().toLowerCase().replace(/\s+/g, '_');
                            meta[key] = dd.textContent.trim();
                        }
                    });

                    const refMatch = meta['reference'] || '';
                    const publishedMatch = meta['publication_date'] || '';
                    const deadlineMatch = meta['closing_date'] || meta['deadline_date'] || '';
                    const countryMatch = meta['contract_location'] || meta['beneficiary_country_or_territory'] || '';
                    const noticeType = meta['notice_type'] || '';

                    const url = titleLink ? titleLink.href : '';
                    const noticeMatch = url.match(/\/Notice\/(\d{6}-\d{4})/);
                    const noticeId = noticeMatch ? noticeMatch[1] : '';

                    return {
                        noticeId: noticeId,
                        title: titleLink ? titleLink.textContent.trim() : '',
                        organization: subHeader ? subHeader.textContent.trim() : '',
                        description: descEl ? descEl.textContent.trim() : '',
                        noticeType: noticeType,
                        published: publishedMatch,
                        deadline: deadlineMatch,
                        country: countryMatch,
                        reference: refMatch,
                        url: url,
                    };
                });
            }""")

            logger.info(f'[FCDO] Page {page_num}: found {len(rows)} raw results')

            for item in rows:
                nid = item.get('noticeId')
                if not nid or nid in seen_set:
                    continue

                org = item.get('organization', '')
                title = item.get('title', '')
                description = item.get('description', '')

                country = item.get('country', '')
                all_text = f'{org} {title} {description} {country}'
                if not _is_fcdo_org(all_text):
                    continue

                if not matches_target_country(all_text):
                    continue

                if nid not in collected:
                    collected[nid] = item

            logger.info(
                f'[FCDO] Page {page_num}: FCDO & NG/LR filtered: {len(collected)}'
            )

        logger.info(f'[FCDO] Total collected (FCDO with NG/LR): {len(collected)}')

        result = list(collected.values())

        if progress_cb:
            progress_cb('processing', 75, f'Processing {len(result)} notices...')

        for item in result:
            item['published_date'] = _parse_date_to_iso(item.get('published'))
            item['deadline_date'] = _parse_date_to_iso(item.get('deadline'))

        logger.info(f'[FCDO] Done — collected {len(result)} new notices')

        if progress_cb:
            progress_cb('done', 100, f'Found {len(result)} new notices')

        return result

    except Exception as e:
        logger.exception(f'[FCDO] Scrape failed: {e}')
        if progress_cb:
            progress_cb('error', 0, f'Error: {e}')
        return []

    finally:
        page.close()

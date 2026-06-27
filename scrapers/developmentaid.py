import logging
import os

from utils import matches_target_country
from .login import ensure_session

logger = logging.getLogger(__name__)


def _parse_deadline(s):
    if not s:
        return None
    from datetime import datetime
    s = s.strip()
    for fmt in ('%d %B %Y', '%B %d, %Y', '%d-%b-%Y', '%Y-%m-%d', '%d.%m.%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%dT00:00:00Z')
        except ValueError:
            continue
    return None

SITE_ID = 'developmentaid'


def scrape_developmentaid(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    email = os.environ.get('DEVELOPMENTAID_EMAIL')
    password = os.environ.get('DEVELOPMENTAID_PASSWORD')
    if not email or not password:
        logger.warning(
            '[DevelopmentAid] DEVELOPMENTAID_EMAIL and/or '
            'DEVELOPMENTAID_PASSWORD not set — skipping'
        )
        if progress_cb:
            progress_cb('skipped', 100, 'Credentials not configured')
        return []

    login_config = {
        'login_url': 'https://www.developmentaid.org/login',
        'form_fields': [
            {
                'selector': (
                    'input[name="email"], input[type="email"], '
                    'input[name="username"]'
                ),
                'value': email,
            },
            {
                'selector': 'input[name="password"], input[type="password"]',
                'value': password,
            },
        ],
        'session_cookie_name': None,
        'auth_check_fn': (
            lambda p: 'Sign In' not in p.inner_text('body')
            and 'Log In' not in p.inner_text('body')
        ),
    }

    if progress_cb:
        progress_cb('logging_in', 5, 'Logging into DevelopmentAid...')

    ensure_session(browser, SITE_ID, login_config)

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 15, 'Loading DevelopmentAid tenders...')

        logger.info('[DevelopmentAid] Navigating to tenders search page...')
        page.goto(
            'https://www.developmentaid.org/tenders/search',
            wait_until='domcontentloaded',
            timeout=60000,
        )

        page.wait_for_timeout(5000)

        if progress_cb:
            progress_cb('parsing', 30, 'Parsing tender cards...')

        items = page.evaluate("""() => {
            const cards = document.querySelectorAll(
                '.tender-card, [class*="tender-item"], '
                '[class*="tender-row"], article[class*="tender"], '
                '[class*="notice-item"], [class*="procurement-item"], '
                '.search-result-item, [class*="search-result"]'
            );
            if (cards.length === 0) {
                const allCards = document.querySelectorAll(
                    'article, .node, .views-row, [class*="card"]'
                );
                return Array.from(allCards).slice(0, 100).map(card => {
                    const link = card.querySelector('a');
                    const text = card.innerText.trim();
                    if (!text || text.length < 20) return null;
                    return {
                        noticeId: link ? (link.href || '').split('/').pop() || text.slice(0, 40) : text.slice(0, 40),
                        title: link ? link.innerText.trim() : text.slice(0, 100),
                        organization: 'DevelopmentAid',
                        fullText: text,
                        country: '',
                        deadline: '',
                        reference: '',
                        published: '',
                        url: link ? link.href : '',
                    };
                }).filter(Boolean);
            }
            return Array.from(cards).map(card => {
                const link = card.querySelector('a');
                const title = link?.innerText?.trim()
                    || card.innerText?.trim().split('\\n')[0]
                    || '';
                const fullText = card.innerText.trim();

                const countryMatch = fullText.match(
                    /(?:Country|Location)\\s*:?\\s*([^\\n]+)/i
                );
                const deadlineMatch = fullText.match(
                    /(?:Deadline|Closing Date|Submission)\\s*:?\\s*([^\\n]+)/i
                );

                return {
                    noticeId: link?.href?.split('/').pop() || title,
                    title,
                    organization: 'DevelopmentAid',
                    fullText,
                    country: countryMatch ? countryMatch[1].trim() : '',
                    deadline: deadlineMatch ? deadlineMatch[1].trim() : '',
                    reference: '',
                    published: '',
                    url: link?.href || '',
                };
            });
        }""")

        logger.info(f'[DevelopmentAid] Found {len(items)} items')

        if progress_cb:
            progress_cb(
                'processing', 60,
                f'Processing {len(items)} items...'
            )

        for item in items:
            nid = item.get('noticeId')
            if not nid or nid in seen_set:
                continue

            country = item.get('country', '') or ''
            all_text = ' '.join([
                item.get('title', '') or '',
                item.get('fullText', '') or '',
                country,
            ])
            if not matches_target_country(all_text):
                continue

            if nid not in collected:
                item['description'] = item.get('fullText', '')[:500]
                item['published_date'] = None
                item['deadline_date'] = _parse_deadline(item.get('deadline'))
                collected[nid] = item

        result = list(collected.values())

        logger.info(
            f'[DevelopmentAid] Done — collected {len(result)} new notices'
        )

        if progress_cb:
            progress_cb('done', 100, f'Found {len(result)} new notices')

        return result

    finally:
        page.close()

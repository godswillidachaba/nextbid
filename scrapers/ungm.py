import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

COUNTRY_IDS = {'Nigeria': '2443', 'Liberia': '2407'}
MAX_NOTICES = 300
SCROLL_ROUNDS = 30


def _parse_date_to_iso(s):
    if not s:
        return None
    try:
        dt = datetime.strptime(s.strip(), '%d-%b-%Y')
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


def _parse_deadline_to_iso(s):
    if not s:
        return None
    m = re.match(
        r'(\d{2}-\w{3}-\d{4})\s+(\d{2}:\d{2})\s+\(GMT\s+([+-]?\d{1,2})\.\d{2}\)',
        s,
    )
    if not m:
        return None
    offset_hours = int(m.group(3))
    try:
        dt = datetime.strptime(f'{m.group(1)} {m.group(2)}', '%d-%b-%Y %H:%M')
        offset = timezone(timedelta(hours=offset_hours))
        dt_utc = dt.replace(tzinfo=offset).astimezone(timezone.utc)
        return dt_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


def _fetch_popup(page, nid):
    try:
        data = page.evaluate("""async (noticeId) => {
            const res = await fetch(
                'https://www.ungm.org/Public/Notice/Popup/' + noticeId
            );
            const html = await res.text();
            const doc = new DOMParser().parseFromString(html, 'text/html');
            const allTitles = doc.querySelectorAll('.title');
            let description = '';
            for (const t of allTitles) {
                if (t.textContent.trim() === 'Description') {
                    const nextDiv = t.nextElementSibling;
                    if (nextDiv) description = nextDiv.textContent.trim();
                    break;
                }
            }
            return { description };
        }""", nid)
        return nid, data.get('description', '')
    except Exception as e:
        logger.warning(f'[UNGM] Failed to fetch popup for {nid}: {e}')
        return nid, ''


def scrape_ungm(browser, seen_set=None, progress_cb=None):
    if seen_set is None:
        seen_set = set()

    page = browser.new_page()
    collected = {}

    try:
        if progress_cb:
            progress_cb('navigating', 5, 'Loading UNGM...')

        logger.info('[UNGM] Navigating to UNGM...')
        page.goto('https://www.ungm.org/Public/Notice', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_selector('#tblNotices', timeout=60000)
        logger.info('[UNGM] Page loaded')

        for country_idx, country in enumerate(('Nigeria', 'Liberia')):
            logger.info(f'[UNGM] Searching for country: {country}')

            base_progress = 10 + (country_idx * 30)

            if progress_cb:
                progress_cb('searching', base_progress, f'Searching {country}...')

            page.evaluate("""(args) => {
                const select = document.querySelector('#selNoticeCountry');
                const input = document.querySelector('#selNoticeCountry-input');
                const hidden = document.querySelector('#isCountrySelected');
                if (select) select.value = args.countryId;
                if (input) input.value = args.countryName;
                if (hidden) hidden.value = '1';
                if (select) select.dispatchEvent(new Event('change', { bubbles: true }));
            }""", {'countryName': country, 'countryId': COUNTRY_IDS[country]})

            page.click('#lnkSearch')

            page.wait_for_timeout(2000)

            total = page.evaluate("""() => {
                const el = document.querySelector('#noticeSearchTotal');
                if (!el) return 0;
                const t = parseInt(el.textContent);
                return isNaN(t) ? 0 : t;
            }""")

            if total == 0:
                page.wait_for_timeout(5000)
                total = page.evaluate("""() => {
                    const el = document.querySelector('#noticeSearchTotal');
                    if (!el) return 0;
                    const t = parseInt(el.textContent);
                    return isNaN(t) ? 0 : t;
                }""")

            logger.info(f'[UNGM] {country}: {total} results total')

            prev_count = 0
            for i in range(SCROLL_ROUNDS):
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(800)
                count = page.evaluate(
                    "() => document.querySelectorAll('#tblNotices .tableBody .tableRow').length"
                )
                logger.info(f'[UNGM] {country}: scroll round {i + 1}, rows loaded: {count}/{total}')
                if count >= total:
                    break
                if count == prev_count and i > 3:
                    break
                prev_count = count

                if progress_cb:
                    scroll_progress = min(int((count / max(total, 1)) * 25), 25)
                    progress_cb(
                        'searching', base_progress + scroll_progress,
                        f'Loading {country} notices ({count}/{total})...'
                    )

            rows = page.evaluate("""() => {
                const rows = document.querySelectorAll('#tblNotices .tableBody .tableRow');
                return Array.from(rows).map(row => {
                    const noticeId = row.getAttribute('data-noticeid');
                    const cells = row.querySelectorAll('.tableCell');
                    const title = row.querySelector('.resultTitle .ungm-title')
                        ?.innerText?.trim();
                    const organization = row.querySelector('.resultAgency span')
                        ?.innerText?.trim();
                    const deadline = row.querySelector('.deadline')
                        ?.innerText?.replace(/\\s+/g, ' ').trim();
                    const reference = row.querySelector('[data-description="Reference"] span')
                        ?.innerText?.trim();
                    const published = cells[3]?.innerText?.trim();
                    const country = cells[7]?.innerText?.trim();
                    return {
                        noticeId,
                        title: title || '',
                        organization: organization || '',
                        country: country || '',
                        deadline: deadline || '',
                        reference: reference || '',
                        published: published || '',
                        url: noticeId
                            ? `https://www.ungm.org/Public/Notice/${noticeId}`
                            : ''
                    };
                });
            }""")

            for item in rows:
                nid = item.get('noticeId')
                if not nid:
                    continue
                if nid in seen_set:
                    continue
                if nid not in collected:
                    collected[nid] = item

            logger.info(
                f'[UNGM] {country}: collected {len(rows)} rows, '
                f'unique total: {len(collected)}'
            )

        result = list(collected.values())[:MAX_NOTICES]
        logger.info(f'[UNGM] Search phase done. Collecting details for {len(result)} notices...')

        if result:
            if progress_cb:
                progress_cb('details', 75, f'Fetching details for {len(result)} notices (parallel)...')

            max_workers = min(10, len(result))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_fetch_popup, page, item['noticeId']): item for item in result}
                for idx, future in enumerate(as_completed(futures)):
                    nid, description = future.result()
                    if nid in collected:
                        collected[nid]['description'] = description
                    if progress_cb:
                        pct = 75 + int(((idx + 1) / max(len(result), 1)) * 10)
                        progress_cb(
                            'details', min(pct, 85),
                            f'Fetched details {idx + 1}/{len(result)}...'
                        )

        for item in result:
            item['published_date'] = _parse_date_to_iso(item.get('published'))
            item['deadline_date'] = _parse_deadline_to_iso(item.get('deadline'))

        if progress_cb:
            progress_cb('saving', 90, 'Saving results...')

        logger.info(f'[UNGM] Done — collected {len(result)} new notices')
        return result

    finally:
        page.close()

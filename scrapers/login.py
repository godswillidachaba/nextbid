import json
import logging
import os

logger = logging.getLogger(__name__)

COOKIE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cookie_path(site_id):
    return os.path.join(COOKIE_DIR, f'.cookies-{site_id}.json')


def _load_cookies(site_id):
    path = _cookie_path(site_id)
    try:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f'Failed to load cookies for "{site_id}": {e}')
    return []


def _save_cookies(site_id, cookies):
    path = _cookie_path(site_id)
    try:
        filtered = [c for c in cookies if not c.get('name', '').startswith('_ga')]
        with open(path, 'w') as f:
            json.dump(filtered, f, indent=2)
        logger.info(f'[login:{site_id}] {len(filtered)} cookies saved to {path}')
    except Exception as e:
        logger.error(f'Failed to save cookies for "{site_id}": {e}')


def ensure_session(browser, site_id, login_config):
    """Ensure an authenticated session for the given site.

    Args:
        browser: playwright.sync_api.Browser instance.
        site_id: str identifier (used for cookie storage filename).
        login_config: dict with keys:
            - login_url: str
            - form_fields: list of {'selector': str, 'value': str}
            - auth_check_fn: callable(page) -> bool
            - session_cookie_name: str or None (unused, kept for compat)

    Returns:
        True if login is (or was already) established.
    """
    login_url = login_config['login_url']
    form_fields = login_config['form_fields']
    auth_check_fn = login_config['auth_check_fn']

    page = browser.new_page()

    try:
        saved_cookies = _load_cookies(site_id)
        if saved_cookies:
            page.context.add_cookies(saved_cookies)

        page.goto(login_url, wait_until='domcontentloaded', timeout=60000)

        if auth_check_fn(page):
            logger.info(f'[login:{site_id}] Already authenticated via cookies')
            return True

        for field in form_fields:
            el = page.query_selector(field['selector'])
            if el:
                el.fill(field['value'])
            else:
                logger.warning(f'[login:{site_id}] Selector "{field["selector"]}" not found')

        submit_btn = page.query_selector(
            'button[type="submit"], input[type="submit"], [type="submit"]'
        )
        if submit_btn:
            submit_btn.click()
        else:
            page.keyboard.press('Enter')

        page.wait_for_timeout(5000)

        verified = auth_check_fn(page)
        if not verified:
            raise RuntimeError(
                f'Login to {site_id} failed — could not verify authenticated session'
            )

        cookies = page.context.cookies()
        _save_cookies(site_id, cookies)
        logger.info(f'[login:{site_id}] Login successful, cookies saved')
        return True

    finally:
        page.close()

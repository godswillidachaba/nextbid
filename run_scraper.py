import argparse
import logging
import os
import sys
import threading
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('run_scraper')

_scrape_progress = {}
_scrape_lock = threading.Lock()


def update_scrape_progress(batch_id, **kw):
    with _scrape_lock:
        if batch_id in _scrape_progress:
            _scrape_progress[batch_id].update(kw)


SCRAPER_SOURCES = [
    ('UNGM', 'scrapers.ungm', 'scrape_ungm'),
    ('WORLDBANK', 'scrapers.worldbank', 'scrape_worldbank'),
    ('GIZ', 'scrapers.giz', 'scrape_giz'),
    ('FCDO', 'scrapers.fcdo', 'scrape_fcdo'),
    ('DEVELOPMENTAID', 'scrapers.developmentaid', 'scrape_developmentaid'),
    ('ACTIONAID', 'scrapers.actionaid', 'scrape_actionaid'),
    ('CRS', 'scrapers.crs', 'scrape_crs'),
    ('AFDB', 'scrapers.afdb', 'scrape_afdb'),
]


def _playwright_context():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = p.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled'],
    )
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
    """)
    return p, browser, context


def run_scrape(source_filter=None, batch_id=None):
    from app import app
    from models import db, Notice, ScrapeRun, BidAnalysis, EmailRecipient, AppSetting
    from agents.agent import LLMProvider
    from agents.emailer import send_analysis_email
    from utils import generate_excel_bytes, retry
    from importlib import import_module

    with app.app_context():
        now = datetime.now(timezone.utc)
        if batch_id is None:
            batch_id = f"SCRP-{now.strftime('%Y%m%d-%H%M%S')}"
        run = ScrapeRun(batch_id=batch_id, status='running', started_at=now)
        db.session.add(run)
        db.session.commit()
        logger.info(f'[Run] Started batch {batch_id}')

        sources_to_run = [s for s in SCRAPER_SOURCES if not source_filter or source_filter.upper() == s[0] or source_filter == 'ALL']
        _scrape_progress[batch_id] = {
            'total_sources': len(sources_to_run),
            'completed_sources': 0,
            'current_source': '',
            'current_message': 'Initializing...',
            'status': 'running',
            'error': '',
        }

        try:
            p, browser, context = _playwright_context()
        except Exception as e:
            run.status = 'failed'
            run.error = f'Playwright init failed: {e}'
            db.session.commit()
            logger.exception('[Run] Playwright init failed')
            return

        total_found = 0
        total_new = 0

        try:
            for src_name, mod_path, func_name in SCRAPER_SOURCES:
                if source_filter and source_filter.upper() != src_name and source_filter != 'ALL':
                    continue

                logger.info(f'[Run] Scraping {src_name}...')
                update_scrape_progress(batch_id, current_source=src_name, current_message=f'Starting {src_name}...')
                try:
                    mod = import_module(mod_path)
                    scraper_func = getattr(mod, func_name)

                    seen_ids = {
                        row[0]
                        for row in db.session.query(Notice.notice_id)
                        .filter(Notice.source == src_name)
                        .all()
                    }

                    def _mk_cb(bid, src):
                        def cb(stage, pct, msg):
                            update_scrape_progress(bid, current_message=f'{src}: {msg}')
                        return cb

                    results = retry(max_attempts=2, delay=5)(scraper_func)(
                        browser, seen_set=seen_ids, progress_cb=_mk_cb(batch_id, src_name)
                    )
                except Exception as e:
                    logger.error(f'[Run] {src_name} scraper failed: {e}')
                    continue

                new_count = 0
                for idx, item in enumerate(results):
                    existing = db.session.query(Notice).filter_by(notice_id=item['noticeId']).first()
                    if existing:
                        continue
                    notice = Notice(
                        notice_id=item['noticeId'],
                        title=item.get('title', ''),
                        organization=item.get('organization', ''),
                        country=item.get('country', ''),
                        deadline=item.get('deadline', ''),
                        deadline_date=_parse_iso(item.get('deadline_date')),
                        reference=item.get('reference', ''),
                        published=item.get('published', ''),
                        published_date=_parse_iso(item.get('published_date')),
                        description=item.get('description', ''),
                        url=item.get('url', ''),
                        source=src_name,
                        batch_id=batch_id,
                    )
                    if notice.deadline_date and notice.deadline_date.replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):
                        continue
                    db.session.add(notice)
                    db.session.flush()
                    new_count += 1

                db.session.commit()
                total_found += len(results)
                total_new += new_count
                update_scrape_progress(batch_id, completed_sources=_scrape_progress[batch_id]['completed_sources'] + 1)
                logger.info(f'[Run] {src_name}: {len(results)} found, {new_count} new')

            run.notices_found = total_found
            run.notices_new = total_new
            db.session.commit()

        except Exception as e:
            run.status = 'failed'
            run.error = f'Scraping failed: {e}'
            update_scrape_progress(batch_id, status='failed', error=str(e))
            db.session.commit()
            logger.exception('[Run] Scraping failed')
        finally:
            try:
                context.close()
                browser.close()
                p.stop()
            except Exception:
                pass

        if run.status == 'failed':
            return batch_id

        if total_new == 0:
            logger.info('[Run] No new notices — skipping analysis & email')
            run.status = 'completed'
            run.completed_at = datetime.now(timezone.utc)
            update_scrape_progress(batch_id, status='completed', current_message='No new notices found')
            db.session.commit()
            return batch_id

        # ── AI Analysis ──
        try:
            provider = os.getenv('AI_PROVIDER', 'openrouter') or AppSetting.get('ai_provider', 'openrouter')
            llm = LLMProvider(provider)

            unanalyzed = (
                db.session.query(Notice)
                .filter(Notice.batch_id == batch_id)
                .all()
            )
            analyzed_count = 0
            for notice in unanalyzed:
                try:
                    notice_data = notice.to_dict()
                    result = llm.analyze(notice_data)

                    existing = BidAnalysis.query.filter_by(notice_id=notice.notice_id).first()
                    if existing:
                        existing.score = result['score']
                        existing.analysis_json = result
                        existing.model_used = result.get('model_used', '')
                        existing.analyzed_at = datetime.now(timezone.utc)
                    else:
                        analysis = BidAnalysis(
                            notice_id=result['notice_id'],
                            score=result['score'],
                            strategic_fit=result.get('strategic_fit', 0),
                            geographic_fit=result.get('geographic_fit', 0),
                            past_performance_fit=result.get('past_performance_fit', 0),
                            win_probability=result.get('win_probability', 0),
                            revenue_potential=result.get('revenue_potential', 0),
                            strategic_relationship_value=result.get('strategic_relationship_value', 0),
                            relevant_unit=result.get('relevant_unit', ''),
                            suggested_position=result.get('suggested_position', 'Monitor'),
                            opportunity_type=result.get('opportunity_type', 'Other'),
                            funding_organization=result.get('funding_organization', ''),
                            geography=result.get('geography', ''),
                            executive_summary=(result.get('executive_summary') or '')[:2000],
                            why_it_fits=(result.get('why_it_fits') or '')[:2000],
                            risks=(result.get('risks') or '')[:2000],
                            red_flags=','.join(result.get('red_flags', []))[:500],
                            consortium_possible=result.get('consortium_possible', False),
                            analysis_json=result,
                            model_used=result.get('model_used', ''),
                        )
                        db.session.add(analysis)
                    db.session.commit()
                    analyzed_count += 1
                except Exception as e:
                    logger.warning(f'[Run] Analysis failed for {notice.notice_id}: {e}')

            run.analyses_completed = analyzed_count
            db.session.commit()
            logger.info(f'[Run] Analyzed {analyzed_count} notices')
        except Exception as e:
            logger.exception('[Run] AI analysis failed')
            run.analyses_completed = 0

        # ── Send Email ──
        try:
            recipients = EmailRecipient.query.all()
            email_to = ','.join(r.email for r in recipients) or os.getenv('EMAIL_TO', '')
            if email_to:
                smtp_host = AppSetting.get('smtp_host') or os.getenv('SMTP_HOST')
                smtp_port = AppSetting.get('smtp_port') or os.getenv('SMTP_PORT')
                smtp_user = AppSetting.get('smtp_user') or os.getenv('SMTP_USER')
                smtp_pass = AppSetting.get('smtp_pass') or os.getenv('SMTP_PASS')
                email_from = AppSetting.get('email_from') or os.getenv('EMAIL_FROM')

                results = (
                    db.session.query(BidAnalysis, Notice)
                    .join(Notice, BidAnalysis.notice_id == Notice.notice_id)
                    .filter(Notice.batch_id == batch_id)
                    .order_by(BidAnalysis.score.desc())
                    .all()
                )

                if results:
                    analyses_data = [
                        {
                            'score': ba.score,
                            'suggested_position': ba.suggested_position,
                            'title': n.title if n else '',
                            'organization': n.organization if n else '',
                            'country': n.country if n else '',
                            'source': n.source if n else '',
                            'url': n.url if n else '',
                            'relevant_unit': ba.relevant_unit,
                            'executive_summary': ba.executive_summary,
                        }
                        for ba, n in results
                    ]
                    notices = [n for ba, n in results]
                    analyses_lookup = {ba.notice_id: ba for ba, n in results}
                    excel_bytes = generate_excel_bytes(notices, analyses_lookup)

                    email_result = send_analysis_email(
                        email_to, analyses_data,
                        smtp_host=smtp_host or None,
                        smtp_port=int(smtp_port) if smtp_port else None,
                        smtp_user=smtp_user or None,
                        smtp_pass=smtp_pass or None,
                        email_from=email_from or None,
                        excel_bytes=excel_bytes,
                    )
                    run.emails_sent = email_result.get('sent', 0)
                    logger.info(f'[Run] Emailed {run.emails_sent} recipient(s)')
        except Exception as e:
            logger.exception('[Run] Email failed')

        run.status = 'completed'
        run.completed_at = datetime.now(timezone.utc)
        update_scrape_progress(batch_id, status='completed', current_message='Done')
        db.session.commit()
        logger.info(f'[Run] Batch {batch_id} complete — {total_found} found, {total_new} new, {run.analyses_completed} analyzed, {run.emails_sent} emailed')
        return batch_id


def _parse_iso(s):
    if not s:
        return None
    try:
        return datetime.strptime(s.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
    except (ValueError, TypeError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run bid scraper pipeline')
    parser.add_argument('--source', default='', help='Source filter (e.g. UNGM) or ALL')
    args = parser.parse_args()
    run_scrape(source_filter=args.source or None)

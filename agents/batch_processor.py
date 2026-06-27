import logging
import os
import threading
from datetime import datetime, timezone
from sqlalchemy import or_

from models import db, Notice, BidAnalysis, ScrapeRun, EmailRecipient, AppSetting

logger = logging.getLogger(__name__)

_analysis_progress = {}
_analysis_results = {}
_analysis_lock = threading.Lock()


class AnalysisProgress:
    def __init__(self, analysis_id: str):
        self.analysis_id = analysis_id
        self.total = 0
        self.completed = 0
        self.errors = 0
        self.status = 'starting'
        self.message = 'Initializing analysis...'
        self.started_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            'analysis_id': self.analysis_id,
            'total': self.total,
            'completed': self.completed,
            'errors': self.errors,
            'status': self.status,
            'message': self.message,
            'progress': int((self.completed / max(self.total, 1)) * 100),
            'started_at': self.started_at.isoformat(),
        }


def run_analysis(analysis_id: str, provider: str = None, source: str = None, batch_id: str = None, app=None, force: bool = False):
    with _analysis_lock:
        prog = AnalysisProgress(analysis_id)
        _analysis_progress[analysis_id] = prog

    prog.status = 'loading'
    prog.message = 'Loading notices...'

    try:
        from agents.agent import LLMProvider
        llm = LLMProvider(provider)

        with app.app_context():
            query = Notice.query.filter()
            if batch_id:
                query = query.filter(Notice.batch_id == batch_id)
            if source:
                query = query.filter(Notice.source == source.upper())

            if not force:
                analyzed_query = db.session.query(BidAnalysis.notice_id)
                if batch_id:
                    analyzed_query = analyzed_query.join(Notice, BidAnalysis.notice_id == Notice.notice_id).filter(Notice.batch_id == batch_id)
                analyzed_ids = {row[0] for row in analyzed_query.all()}
                if analyzed_ids:
                    query = query.filter(Notice.notice_id.notin_(analyzed_ids))
                    prog.message = f'Skipping {len(analyzed_ids)} already analyzed notices...'

            notices = query.filter(
                or_(Notice.deadline_date == None, Notice.deadline_date >= datetime.now(timezone.utc).replace(tzinfo=None))
            ).order_by(Notice.scraped_at.desc()).limit(200).all()

        prog.total = len(notices)
        if not notices:
            prog.status = 'done'
            prog.message = 'No new notices to analyze'
            if app and batch_id:
                with app.app_context():
                    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
                    if run:
                        count = BidAnalysis.query.join(Notice, BidAnalysis.notice_id == Notice.notice_id).filter(Notice.batch_id == batch_id).count()
                        run.analyses_completed = count
                        db.session.commit()
            return

        prog.status = 'running'
        prog.message = f'Analyzing {len(notices)} notices...'

        analyzed = 0

        for notice in notices:
            try:
                notice_data = notice.to_dict() if hasattr(notice, 'to_dict') else notice
                result = llm.analyze(notice_data)
                with app.app_context():
                    existing = BidAnalysis.query.filter_by(notice_id=notice_data.get('notice_id') or notice_data.get('noticeId', '')).first()
                    if existing:
                        existing.score = result['score']
                        existing.analysis_json = result
                        existing.model_used = result.get('model_used', '')
                        existing.analyzed_at = datetime.now(timezone.utc)
                    else:
                        analysis = BidAnalysis(
                            notice_id=result['notice_id'],
                            score=result['score'],
                            relevant_unit=result.get('relevant_unit', ''),
                            suggested_position=result.get('suggested_position', ''),
                            opportunity_type=result.get('opportunity_type', ''),
                            funding_organization=result.get('funding_organization', ''),
                            geography=result.get('geography', ''),
                            executive_summary=result.get('executive_summary', '')[:2000],
                            why_it_fits=result.get('why_it_fits', '')[:2000],
                            risks=result.get('risks', '')[:2000],
                            red_flags=','.join(result.get('red_flags', []))[:500],
                            consortium_possible=result.get('consortium_possible', False),
                            analysis_json=result,
                            model_used=result.get('model_used', ''),
                        )
                        db.session.add(analysis)
                    db.session.commit()
                analyzed += 1
                with _analysis_lock:
                    prog.completed = analyzed
                    prog.message = f'Analyzed {analyzed}/{len(notices)}...'
                    if analyzed % 5 == 0:
                        logger.info(f'[Analysis] {analyzed}/{len(notices)} processed')
            except Exception as e:
                logger.exception(f'Agent failed for notice')
                with _analysis_lock:
                    prog.errors += 1

        prog.status = 'done'
        prog.message = f'Analysis complete — {prog.completed - prog.errors} analyzed, {prog.errors} errors'

        if app:
            with app.app_context():
                run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
                if run:
                    run.analyses_completed = (run.analyses_completed or 0) + (prog.completed - prog.errors)
                    db.session.commit()

        # Auto-email if configured
        with app.app_context():
            recipients = EmailRecipient.query.all()
            email_to = ','.join(r.email for r in recipients) or os.getenv('EMAIL_TO', '')
        if email_to:
            try:
                    from agents.emailer import send_analysis_email
                    from utils import generate_excel_bytes
                    with app.app_context():
                        smtp_host = AppSetting.get('smtp_host') or None
                        smtp_port = AppSetting.get('smtp_port') or None
                        smtp_user = AppSetting.get('smtp_user') or None
                        smtp_pass = AppSetting.get('smtp_pass') or None
                        email_from = AppSetting.get('email_from') or None

                        results = (
                            db.session.query(BidAnalysis, Notice)
                            .join(Notice, BidAnalysis.notice_id == Notice.notice_id)
                            .order_by(BidAnalysis.score.desc())
                            .limit(100)
                            .all()
                        )
                        analyses_data = [
                            {
                                'score': ba.score,
                                'suggested_position': ba.suggested_position,
                                'title': n.title if n else '',
                                'organization': n.organization if n else '',
                                'country': n.country if n else '',
                                'source': n.source if n else '',
                                'relevant_unit': ba.relevant_unit,
                                'executive_summary': ba.executive_summary,
                                'url': n.url if n else '',
                            }
                            for ba, n in results
                        ]
                        if analyses_data:
                            notices = [n for ba, n in results]
                            analyses_lookup = {ba.notice_id: ba for ba, n in results}
                            excel_bytes = generate_excel_bytes(notices, analyses_lookup)
                            result = send_analysis_email(
                                email_to, analyses_data,
                                smtp_host=smtp_host,
                                smtp_port=int(smtp_port) if smtp_port else None,
                                smtp_user=smtp_user,
                                smtp_pass=smtp_pass,
                                email_from=email_from,
                                excel_bytes=excel_bytes,
                            )
                        if result.get('error'):
                            logger.warning(f'[Analysis] Auto-email failed: {result["error"]}')
                            prog.message += f' | Email failed: {result["error"]}'
                        else:
                            prog.message += f' | Emailed to {result["sent"]} recipient(s)'
            except Exception as e:
                logger.warning(f'[Analysis] Auto-email failed: {e}')
                prog.message += f' | Email error: {e}'

    except Exception as e:
        logger.exception('[Analysis] Batch failed')
        prog.status = 'error'
        prog.message = str(e)

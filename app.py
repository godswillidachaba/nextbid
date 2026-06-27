import logging
import os
import smtplib
import threading
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from functools import wraps

from flask import Flask, Response, jsonify, render_template, request, session

from config import Config
from models import db, Notice, BidAnalysis, ScrapeRun, EmailRecipient, AppSetting, User

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
)
logger = logging.getLogger('bidz')

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
db.init_app(app)

with app.app_context():
    db.create_all()
    inspector = db.inspect(db.engine)
    columns = [c['name'] for c in inspector.get_columns('notices')]
    if 'batch_id' not in columns:
        db.session.execute(db.text('ALTER TABLE notices ADD COLUMN batch_id VARCHAR(30)'))
        db.session.execute(db.text('CREATE INDEX IF NOT EXISTS ix_notices_batch_id ON notices(batch_id)'))
    tables = inspector.get_table_names()
    if 'scrape_runs' not in tables:
        db.create_all()
    if 'users' in inspector.get_table_names():
        if User.query.count() == 0:
            user = User(username='info', email='info@thenextier.com', name='Administrator')
            user.set_password('@Nextier2026')
            db.session.add(user)
            db.session.commit()
            logger.info('Default user created: info@thenextier.com / @Nextier2026')
    db.session.commit()


# ── Frontend ──

@app.route('/')
def index():
    return render_template('admin.html')


# ── Auth Decorator ──

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


# ── Auth Routes ──

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(force=True)
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({'error': 'Username and password required'}), 400

    user = User.query.filter(
        (User.username == username) | (User.email == username)
    ).first()

    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid credentials'}), 401

    session['user_id'] = user.id
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=7)
    return jsonify({'user': user.to_dict()})


@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'status': 'ok'})


@app.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'user': None})
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return jsonify({'user': None})
    return jsonify({'user': user.to_dict()})


def send_reset_email(to_email, reset_link):
    smtp_host = Config.SMTP_HOST
    smtp_port = Config.SMTP_PORT
    smtp_user = Config.SMTP_USER
    smtp_pass = Config.SMTP_PASS
    email_from = Config.EMAIL_FROM

    if not smtp_user or not smtp_pass:
        raise Exception('SMTP not configured')

    msg = MIMEText(f"""\
You requested a password reset for your NextBid account.

Click the link below to reset your password:
{reset_link}

This link expires in 1 hour.

If you didn't request this, please ignore this email.
---
NextBid Executive Intelligence Operating System
""")
    msg['Subject'] = 'NextBid \u2014 Password Reset'
    msg['From'] = email_from
    msg['To'] = to_email

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json(force=True)
    email = data.get('email', '').strip().lower()

    if not email:
        return jsonify({'error': 'Email required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'message': 'If that email exists, a reset link has been sent.'}), 200

    token = user.generate_reset_token()
    reset_link = f"{request.host_url}?reset_token={token}"

    try:
        send_reset_email(user.email, reset_link)
        return jsonify({'message': 'If that email exists, a reset link has been sent.'}), 200
    except Exception as e:
        logger.warning(f'Failed to send reset email: {e}')
        return jsonify({
            'message': 'Password reset link generated (email unavailable).',
            'reset_link': reset_link,
            'token': token,
        }), 200


@app.route('/api/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(force=True)
    token = data.get('token', '').strip()
    password = data.get('password', '')

    if not token or not password:
        return jsonify({'error': 'Token and password required'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    user = User.query.filter_by(reset_token=token).first()
    now = datetime.utcnow()
    if not user or not user.reset_token_expires or user.reset_token_expires < now:
        return jsonify({'error': 'Invalid or expired token'}), 400

    user.set_password(password)
    user.clear_reset_token()
    db.session.commit()

    return jsonify({'message': 'Password reset successful. You can now sign in.'}), 200


# ── Health ──

@app.route('/api/health')
def health():
    db_ok = False
    try:
        Notice.query.count()
        db_ok = True
    except Exception:
        pass
    return jsonify({'status': 'ok' if db_ok else 'error', 'db_ok': db_ok})


# ── Stats ──

@app.route('/api/stats')
@login_required
def stats():
    total_notices = db.session.query(db.func.count(Notice.id)).scalar() or 0
    total_analyzed = db.session.query(db.func.count(BidAnalysis.id)).scalar() or 0
    total_recipients = db.session.query(db.func.count(EmailRecipient.id)).scalar() or 0
    last_run = ScrapeRun.query.order_by(ScrapeRun.started_at.desc()).first()
    source_counts = [
        {'source': r[0] or 'Unknown', 'count': r[1]}
        for r in db.session.query(Notice.source, db.func.count(Notice.id))
        .group_by(Notice.source).order_by(db.func.count(Notice.id).desc()).all()
    ]
    return jsonify({
        'total_notices': total_notices,
        'total_analyzed': total_analyzed,
        'total_recipients': total_recipients,
        'last_run': last_run.to_dict() if last_run else None,
        'source_counts': source_counts,
    })


# ── Scrape Runs ──

@app.route('/api/runs')
@login_required
def list_runs():
    limit = request.args.get('limit', 20, type=int)
    runs = ScrapeRun.query.order_by(ScrapeRun.started_at.desc()).limit(limit).all()
    return jsonify([r.to_dict() for r in runs])


@app.route('/api/runs/<batch_id>')
@login_required
def get_run(batch_id):
    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
    if not run:
        return jsonify({'error': 'not found'}), 404
    notices = (
        Notice.query.filter_by(batch_id=batch_id)
        .order_by(Notice.source)
        .all()
    )
    data = run.to_dict()
    data['notices'] = [n.to_dict() for n in notices]
    analyses = {
        ba.notice_id: ba
        for ba in BidAnalysis.query.filter(
            BidAnalysis.notice_id.in_([n.notice_id for n in notices])
        ).all()
    }
    for n in data['notices']:
        a = analyses.get(n['notice_id'])
        if a:
            n['analysis'] = {'score': a.score, 'suggested_position': a.suggested_position, 'relevant_unit': a.relevant_unit}
    return jsonify(data)


@app.route('/api/runs/<batch_id>', methods=['DELETE'])
@login_required
def delete_run(batch_id):
    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
    if not run:
        return jsonify({'error': 'Run not found'}), 404

    notice_ids = [row[0] for row in db.session.query(Notice.notice_id).filter(Notice.batch_id == batch_id).all()]
    if notice_ids:
        BidAnalysis.query.filter(BidAnalysis.notice_id.in_(notice_ids)).delete()
    Notice.query.filter_by(batch_id=batch_id).delete()
    db.session.delete(run)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@app.route('/api/runs/<batch_id>/export')
@login_required
def export_run(batch_id):
    from utils import generate_excel_bytes
    from io import BytesIO

    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
    if not run:
        return jsonify({'error': 'Run not found'}), 404

    notices = Notice.query.filter_by(batch_id=batch_id).order_by(Notice.source).all()
    analyses_lookup = {
        ba.notice_id: ba
        for ba in BidAnalysis.query.filter(
            BidAnalysis.notice_id.in_([n.notice_id for n in notices])
        ).all()
    }

    excel_bytes = generate_excel_bytes(notices, analyses_lookup)
    return Response(
        excel_bytes.getvalue(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename="intelligence_{batch_id}.xlsx"'},
    )


# ── On-Demand Scrape ──

@app.route('/api/scrape', methods=['POST'])
@login_required
def trigger_scrape():
    source = request.args.get('source', '')
    from run_scraper import run_scrape, _scrape_progress
    batch_id = f"SCRP-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    _scrape_progress[batch_id] = {
        'total_sources': 0,
        'completed_sources': 0,
        'current_source': '',
        'current_message': 'Starting...',
        'status': 'running',
        'error': '',
    }
    t = threading.Thread(target=_run_scrape_wrapper, args=(source, batch_id), daemon=True)
    t.start()
    return jsonify({'status': 'started', 'batch_id': batch_id, 'message': 'Scan started'})


def _run_scrape_wrapper(source='', batch_id=None):
    from run_scraper import run_scrape
    try:
        run_scrape(source_filter=source or None, batch_id=batch_id)
    except Exception as e:
        logger.exception('On-demand scrape failed')


@app.route('/api/scrape/progress/<batch_id>')
@login_required
def get_scrape_progress(batch_id):
    from run_scraper import _scrape_progress
    prog = _scrape_progress.get(batch_id)
    if not prog:
        return jsonify({'error': 'No progress data'}), 404
    return jsonify(prog)


# ── Send Email for Run ──

@app.route('/api/runs/<batch_id>/email', methods=['POST'])
@login_required
def send_run_email(batch_id):
    from agents.emailer import send_analysis_email
    from utils import generate_excel_bytes

    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
    if not run:
        return jsonify({'error': 'Run not found'}), 404
    if run.status != 'completed':
        return jsonify({'error': 'Run must be completed to send email'}), 400

    recipients = EmailRecipient.query.all()
    if not recipients:
        return jsonify({'sent': 0, 'error': 'No email recipients configured'}), 400

    email_to = ','.join(r.email for r in recipients)

    smtp_host = AppSetting.get('smtp_host') or os.getenv('SMTP_HOST')
    smtp_port = AppSetting.get('smtp_port') or os.getenv('SMTP_PORT')
    smtp_user = AppSetting.get('smtp_user') or os.getenv('SMTP_USER')
    smtp_pass = AppSetting.get('smtp_pass') or os.getenv('SMTP_PASS')
    email_from = AppSetting.get('email_from') or os.getenv('EMAIL_FROM')

    analyzed = (
        db.session.query(BidAnalysis, Notice)
        .join(Notice, BidAnalysis.notice_id == Notice.notice_id)
        .filter(Notice.batch_id == batch_id)
        .order_by(BidAnalysis.score.desc())
        .all()
    )

    if analyzed:
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
            for ba, n in analyzed
        ]
        notices = [n for ba, n in analyzed]
        analyses_lookup = {ba.notice_id: ba for ba, n in analyzed}
    else:
        # Fallback: no AI analysis — use raw notices
        notices = Notice.query.filter_by(batch_id=batch_id).order_by(Notice.source).all()
        analyses_data = [
            {
                'score': 0,
                'suggested_position': 'Monitor',
                'title': n.title or '',
                'organization': n.organization or '',
                'country': n.country or '',
                'source': n.source or '',
                'url': n.url or '',
                'relevant_unit': '',
                'executive_summary': '',
            }
            for n in notices
        ]
        analyses_lookup = {}

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

    run.emails_sent = (run.emails_sent or 0) + email_result.get('sent', 0)
    db.session.commit()

    return jsonify({
        'sent': email_result.get('sent', 0),
        'failed': email_result.get('failed', 0),
        'results': email_result.get('results', []),
    })


# ── On-Demand Analysis ──

@app.route('/api/analyze/<batch_id>', methods=['POST'])
@login_required
def trigger_analysis(batch_id):
    from agents.batch_processor import run_analysis
    run = ScrapeRun.query.filter_by(batch_id=batch_id).first()
    if not run:
        return jsonify({'error': 'Batch not found'}), 404
    force = request.args.get('force', 'false').lower() == 'true'
    analysis_id = f"ANL-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    t = threading.Thread(target=run_analysis, args=(analysis_id,), kwargs={'batch_id': batch_id, 'app': app, 'force': force}, daemon=True)
    t.start()
    return jsonify({'status': 'started', 'analysis_id': analysis_id, 'message': f'AI analysis started for {batch_id}'})


@app.route('/api/analysis/progress/<analysis_id>')
@login_required
def get_analysis_progress(analysis_id):
    from agents.batch_processor import _analysis_progress
    prog = _analysis_progress.get(analysis_id)
    if not prog:
        return jsonify({'status': 'not_found'}), 404
    return jsonify(prog.to_dict())


# ── Email Recipients ──

@app.route('/api/recipients')
@login_required
def list_recipients():
    recipients = EmailRecipient.query.order_by(EmailRecipient.created_at.desc()).all()
    return jsonify([r.to_dict() for r in recipients])


@app.route('/api/recipients', methods=['POST'])
@login_required
def add_recipient():
    data = request.get_json(force=True)
    email = data.get('email', '').strip().lower()
    if not email:
        return jsonify({'error': 'Email required'}), 400
    existing = EmailRecipient.query.filter_by(email=email).first()
    if existing:
        return jsonify({'status': 'exists', 'recipient': existing.to_dict()})
    name = data.get('name', '').strip() or None
    r = EmailRecipient(email=email, name=name)
    db.session.add(r)
    db.session.commit()
    return jsonify({'status': 'added', 'recipient': r.to_dict()}), 201


@app.route('/api/recipients/<int:recipient_id>', methods=['DELETE'])
@login_required
def delete_recipient(recipient_id):
    r = db.session.get(EmailRecipient, recipient_id)
    if not r:
        return jsonify({'error': 'not found'}), 404
    db.session.delete(r)
    db.session.commit()
    return jsonify({'status': 'deleted'})


# ── Settings ──

@app.route('/api/settings', methods=['GET'])
@login_required
def get_settings():
    rows = AppSetting.query.all()
    return jsonify({r.key: r.value for r in rows})


@app.route('/api/settings', methods=['POST'])
@login_required
def update_settings():
    data = request.get_json(force=True)
    for key, value in data.items():
        AppSetting.set(key, str(value) if value is not None else '')
    return jsonify({'status': 'ok'})


@app.route('/api/settings/test-email', methods=['POST'])
@login_required
def test_email():
    from agents.emailer import send_analysis_email
    recipients = EmailRecipient.query.all()
    if not recipients:
        return jsonify({'sent': 0, 'message': 'No recipients configured'})
    to_addrs = ','.join(r.email for r in recipients)

    smtp_host = AppSetting.get('smtp_host') or os.getenv('SMTP_HOST')
    smtp_port = AppSetting.get('smtp_port') or os.getenv('SMTP_PORT')
    smtp_user = AppSetting.get('smtp_user') or os.getenv('SMTP_USER')
    smtp_pass = AppSetting.get('smtp_pass') or os.getenv('SMTP_PASS')
    email_from = AppSetting.get('email_from') or os.getenv('EMAIL_FROM')

    dummy = [{
        'score': 100, 'suggested_position': 'Test', 'title': 'Test email from Nextier',
        'organization': 'Nextier', 'country': '\u2014', 'source': '\u2014',
        'relevant_unit': '\u2014', 'executive_summary': 'This is a test email to confirm SMTP settings work.',
        'url': '',
    }]
    result = send_analysis_email(
        to_addrs, dummy,
        smtp_host=smtp_host or None,
        smtp_port=int(smtp_port) if smtp_port else None,
        smtp_user=smtp_user or None,
        smtp_pass=smtp_pass or None,
        email_from=email_from or None,
    )
    sent = result.get('sent', 0)
    if sent > 0:
        return jsonify({'sent': sent, 'message': f'Test email sent to {sent} recipient(s)'})
    return jsonify({'sent': 0, 'message': result.get('error') or 'Failed to send'}), 500


@app.route('/api/system-prompt')
@login_required
def get_system_prompt():
    from pathlib import Path
    path = Path(__file__).parent / 'system_prompt.md'
    return jsonify({'content': path.read_text()})


# ── User Management ──

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    data = request.get_json(force=True)
    username = data.get('username', '').strip()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()

    if not username or not email or not password:
        return jsonify({'error': 'Username, email, and password required'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already taken'}), 409

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(username=username, email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(force=True)

    email = data.get('email', '').strip().lower()
    if email and email != user.email:
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'Email already registered'}), 409
        user.email = email

    name = data.get('name')
    if name is not None:
        user.name = name.strip()

    db.session.commit()
    return jsonify(user.to_dict())


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if user_id == session.get('user_id'):
        return jsonify({'error': 'Cannot delete yourself'}), 400

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    return jsonify({'status': 'deleted'})


@app.route('/api/users/<int:user_id>/password', methods=['PUT'])
@login_required
def change_user_password(user_id):
    if user_id != session.get('user_id'):
        return jsonify({'error': 'You can only change your own password'}), 403

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json(force=True)
    old = data.get('old_password', '')
    new = data.get('new_password', '')

    if not old or not new:
        return jsonify({'error': 'Old and new passwords required'}), 400

    if not user.check_password(old):
        return jsonify({'error': 'Current password is incorrect'}), 403

    if len(new) < 6:
        return jsonify({'error': 'New password must be at least 6 characters'}), 400

    user.set_password(new)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ── SPA catch-all (serve admin.html for all frontend routes) ──

@app.route('/<path:path>')
def spa_fallback(path):
    return render_template('admin.html')


if __name__ == '__main__':
    app.run(debug=True, use_reloader=False, threaded=True, host='0.0.0.0', port=Config.PORT)

"""Durable, grouped login alerts with per-account limits shared by all workers."""
from __future__ import annotations

import asyncio
from datetime import datetime
import json
import secrets
import time

from sqlalchemy import delete, select, update

from app.database import SessionLocal
from app.logging_config import logger
from app.models import EmailDeliveryJob, LoginAlertDeliveryState, LoginAlertEvent, LoginUnlockVerification, User
from app.services.authentication.mail import send_device_login_alert_email
from app.settings import VIETNAM_TZ

ALERT_INTERVAL_SECONDS = 15 * 60
ALERT_DAILY_LIMIT = 10
MAX_SUMMARY_LABELS = 10


def _day_start(now):
    return int(datetime.fromtimestamp(now, VIETNAM_TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


def _account_state(db, user_id):
    # Always acquire the account before any delivery row. Selecting only the ID
    # avoids overwriting the login caller's unflushed User changes.
    if db.scalar(select(User.id).where(User.id == user_id).with_for_update()) is None:
        return None
    state = db.get(LoginAlertDeliveryState, user_id, populate_existing=True)
    if state is None:
        state = LoginAlertDeliveryState(user_id=user_id, day_started_at=0, daily_count=0, next_allowed_at=0)
        db.add(state)
        db.flush()
    return state


def _refresh_day(state, now):
    day = _day_start(now)
    if state.day_started_at != day:
        state.day_started_at, state.daily_count = day, 0
    return day


def _job(db, job_id):
    return db.get(EmailDeliveryJob, job_id, populate_existing=True) if job_id else None


def _earliest_send(state, now):
    due = max(now, state.next_allowed_at)
    if state.day_started_at == _day_start(now) and state.daily_count >= ALERT_DAILY_LIMIT:
        due = max(due, state.day_started_at + 86400)
    return due


def _payload(label, logged_in_at):
    timestamp = logged_in_at.isoformat()
    return {"label": label, "logged_in_at": timestamp, "first_logged_in_at": timestamp,
            "count": 1, "labels": [label]}


def queue_login_alert(db, user, label, logged_in_at):
    """Called inside the same transaction as login; no network or commit here."""
    state = _account_state(db, user.id)
    if state is None:
        return None
    now = int(time.time())
    _refresh_day(state, now)
    job = _job(db, state.pending_job_id)
    # A claimed/retried email is immutable. New events go into the next batch
    # so events arriving while SMTP is sending are never silently omitted.
    if not job or job.sent_at is not None or job.attempts or job.lease_token:
        job = EmailDeliveryJob(id=secrets.token_urlsafe(24), user_id=user.id, recipient=user.email,
            payload_json=json.dumps(_payload(label, logged_in_at)), attempts=0,
            next_attempt_at=_earliest_send(state, now), lease_until=0, created_at=now, quota_day=0)
        db.add(job)
        state.pending_job_id = job.id
    else:
        payload = json.loads(job.payload_json)
        payload["count"] = int(payload.get("count", 1)) + 1
        payload["first_logged_in_at"] = min(payload.get("first_logged_in_at", payload["logged_in_at"]), logged_in_at.isoformat())
        payload["logged_in_at"] = max(payload["logged_in_at"], logged_in_at.isoformat())
        labels = payload.setdefault("labels", [payload["label"]])
        if label not in labels and len(labels) < MAX_SUMMARY_LABELS:
            labels.append(label)
        job.payload_json = json.dumps(payload)
        job.next_attempt_at = max(job.next_attempt_at, _earliest_send(state, now))
    db.flush()
    db.add(LoginAlertEvent(id=secrets.token_urlsafe(24), user_id=user.id, job_id=job.id,
                          label=label, logged_in_at=logged_in_at.isoformat()))
    return job.id


def _claim_alert(job_id, now):
    with SessionLocal() as db:
        query = select(EmailDeliveryJob.id, EmailDeliveryJob.user_id).where(EmailDeliveryJob.sent_at.is_(None),
            EmailDeliveryJob.next_attempt_at <= now, EmailDeliveryJob.lease_until <= now)
        if job_id is not None:
            query = query.where(EmailDeliveryJob.id == job_id)
        candidate = db.execute(query.order_by(EmailDeliveryJob.next_attempt_at, EmailDeliveryJob.created_at,
                                              EmailDeliveryJob.id).limit(1)).first()
        if candidate is None:
            return None, False
        state = _account_state(db, candidate.user_id)
        job = _job(db, candidate.id)
        if not state or not job or job.sent_at is not None or job.next_attempt_at > now or job.lease_until > now:
            return None, True
        day = _refresh_day(state, now)
        active = _job(db, state.active_job_id)
        if active and active.id != job.id and active.sent_at is None:
            job.next_attempt_at = max(now + 15, state.next_allowed_at, active.next_attempt_at, active.lease_until)
            db.commit()
            return None, True
        # Legacy queued emails also pass through these checks. Reserve at most
        # ten distinct alerts per local day; retries reuse the day's reservation.
        due = _earliest_send(state, now)
        if job.quota_day != day and (state.daily_count >= ALERT_DAILY_LIMIT or (not job.attempts and due > now)):
            job.next_attempt_at = due
            db.commit()
            return None, True
        if job.quota_day != day:
            state.daily_count += 1
            job.quota_day = day
        if not job.attempts:
            state.next_allowed_at = now + ALERT_INTERVAL_SECONDS
        # A deferred digest must use the account's current address; otherwise
        # grouping after an email change could disclose later logins to the old one.
        job.recipient = db.scalar(select(User.email).where(User.id == job.user_id))
        state.active_job_id = job.id
        if state.pending_job_id == job.id:
            state.pending_job_id = None
        lease = secrets.token_urlsafe(24)
        job.lease_token, job.lease_until = lease, now + 300
        job.attempts += 1
        claimed = (job.id, job.user_id, job.recipient, job.payload_json, job.attempts, lease)
        db.commit()
        return claimed, True


def _finish_alert(claimed, sent):
    job_id, user_id, _, _, attempts, lease = claimed
    now = int(time.time())
    with SessionLocal() as db:
        state = _account_state(db, user_id)
        job = _job(db, job_id)
        if not state or not job or job.lease_token != lease:
            return
        job.lease_token, job.lease_until = None, 0
        if sent:
            day = _refresh_day(state, now)
            if job.quota_day != day:
                # A send may start before midnight and finish after it. Count
                # that accepted email in the new day before allowing another one.
                state.daily_count += 1
                job.quota_day = day
            job.sent_at = now
            if state.active_job_id == job_id:
                state.active_job_id = None
            state.next_allowed_at = max(state.next_allowed_at, now + ALERT_INTERVAL_SECONDS)
        else:
            job.next_attempt_at = now + min(3600, 30 * 2 ** min(attempts - 1, 7))
        pending = _job(db, state.pending_job_id)
        if pending and pending.sent_at is None:
            pending.next_attempt_at = max(pending.next_attempt_at, _earliest_send(state, now),
                                          job.next_attempt_at if not sent else 0)
        db.commit()


def deliver_login_alert(job_id=None):
    claimed, handled = _claim_alert(job_id, int(time.time()))
    if claimed is None:
        return handled
    _, _, recipient, payload_json, _, _ = claimed
    try:
        payload = json.loads(payload_json)
        options = {}
        if payload.get("count", 1) > 1:
            options = {"count": payload["count"], "first_logged_in_at": datetime.fromisoformat(payload["first_logged_in_at"]),
                       "device_labels": payload["labels"]}
        sent = send_device_login_alert_email(recipient, payload["label"],
                    datetime.fromisoformat(payload["logged_in_at"]), **options)
    except Exception:
        sent = False
    _finish_alert(claimed, sent)
    if not sent:
        logger.warning("Login alert queued for another delivery attempt")
    return True


def deliver_due_alerts():
    for _ in range(5):
        if not deliver_login_alert():
            break
    with SessionLocal() as db:
        # Keep the event history when old delivered emails are cleaned up.
        expired = select(EmailDeliveryJob.id).where(EmailDeliveryJob.sent_at < int(time.time()) - 7 * 86400)
        db.execute(update(LoginAlertEvent).where(LoginAlertEvent.job_id.in_(expired)).values(job_id=None))
        db.execute(delete(EmailDeliveryJob).where(EmailDeliveryJob.sent_at < int(time.time()) - 7 * 86400))
        db.execute(delete(LoginUnlockVerification).where(LoginUnlockVerification.expires_at < int(time.time()) - 86400))
        db.commit()


async def email_delivery_worker():
    while True:
        try:
            await asyncio.to_thread(deliver_due_alerts)
        except Exception:
            logger.warning("Login alert delivery will be retried after a storage error")
        await asyncio.sleep(15)

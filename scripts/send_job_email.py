#!/usr/bin/env python3
"""Email the weekly job-scan results in job-scan/latest.json through Gmail.

Credentials come from environment variables (GitHub Actions secrets), never from files:
  Option A, Gmail app password:  GMAIL_ADDRESS + GMAIL_APP_PASSWORD
  Option B, Gmail API (OAuth):    GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN
                                  (+ GMAIL_ADDRESS if you want it shown as the sender)
Recipient: EMAIL_TO if set, otherwise GMAIL_ADDRESS.

Usage:
  python scripts/send_job_email.py job-scan/latest.json            # send
  python scripts/send_job_email.py job-scan/latest.json --preview  # write preview.html, don't send
"""
import base64
import html
import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import date
from email.message import EmailMessage

ACCENT = "#1d5e49"
MUTED = "#5b6b64"


def safe_url(u):
    u = (u or "").strip()
    return u if u.startswith(("https://", "http://")) else ""


def nice_date(iso):
    try:
        d = date.fromisoformat(iso)
        return d.strftime("%a %b ") + str(d.day)
    except (TypeError, ValueError):
        return iso or ""


def job_line(j):
    bits = [j.get("company"), j.get("location"), j.get("payText") or "pay not posted"]
    return " · ".join(b for b in bits if b)


def section_text(title, jobs):
    if not jobs:
        return ""
    out = [title.upper()]
    for i, j in enumerate(jobs, 1):
        out.append(f"{i}. {j.get('title')} · {job_line(j)}")
        if j.get("why"):
            out.append(f"   {j['why']}")
        if safe_url(j.get("url")):
            out.append(f"   {safe_url(j['url'])}")
    return "\n".join(out) + "\n\n"


def section_html(title, jobs):
    if not jobs:
        return ""
    rows = []
    for j in jobs:
        url = safe_url(j.get("url"))
        t = html.escape(j.get("title") or "Untitled role")
        link = f'<a href="{html.escape(url)}" style="color:{ACCENT};font-weight:600;text-decoration:none">{t}</a>' if url else f"<strong>{t}</strong>"
        why = f'<div style="margin-top:3px">{html.escape(j["why"])}</div>' if j.get("why") else ""
        rows.append(
            f'<li style="margin:0 0 14px">{link}'
            f'<div style="color:{MUTED};font-size:14px">{html.escape(job_line(j))}</div>{why}</li>'
        )
    return (f'<h2 style="font-size:16px;margin:22px 0 8px">{html.escape(title)}</h2>'
            f'<ol style="padding-left:20px;margin:0">{"".join(rows)}</ol>')


def build_message(data):
    strong, good = data.get("strong") or [], data.get("good") or []
    still, missed = data.get("stillOpen") or [], data.get("couldntCheck") or []
    n = len(strong) + len(good)
    when = nice_date(data.get("date"))
    tracker = safe_url(data.get("trackerUrl"))
    checked = data.get("employersChecked")

    subject = f"Job matches · {when} · {n} new" if n else f"Job matches · {when} · nothing new"
    intro = f"{n} new match{'es' if n != 1 else ''}" + (f" from {checked} employers checked" if checked else "") + "."

    text = [intro]
    if tracker:
        text.append(f"All leads and statuses: {tracker}")
    text.append("")
    body_text = "\n".join(text) + "\n" + section_text("Strong fits", strong) + section_text("Good fits", good)
    if still:
        body_text += "STILL OPEN FROM EARLIER WEEKS\n" + "\n".join(
            f"- {s.get('title')} · {s.get('company', '')} {safe_url(s.get('url'))}" for s in still) + "\n\n"
    if missed:
        body_text += "Couldn't check this week: " + ", ".join(missed) + "\n"
    if data.get("note"):
        body_text += data["note"] + "\n"

    still_html = ""
    if still:
        items = "".join(
            f'<li style="margin:0 0 6px"><a href="{html.escape(safe_url(s.get("url")))}" style="color:{ACCENT}">'
            f'{html.escape(s.get("title") or "")}</a> <span style="color:{MUTED}">· {html.escape(s.get("company") or "")}</span></li>'
            for s in still if safe_url(s.get("url")))
        still_html = f'<h2 style="font-size:16px;margin:22px 0 8px">Still open from earlier weeks</h2><ul style="padding-left:20px;margin:0">{items}</ul>'
    missed_html = (f'<p style="color:{MUTED};font-size:14px;margin-top:22px">Couldn\'t check this week: '
                   f'{html.escape(", ".join(missed))}</p>') if missed else ""
    note_html = f'<p style="color:{MUTED};font-size:14px">{html.escape(data["note"])}</p>' if data.get("note") else ""
    tracker_html = (f'<p style="margin:6px 0 0"><a href="{html.escape(tracker)}" style="color:{ACCENT}">'
                    f'Open Monday Job Leads</a> to mark jobs Interested, Applied or Pass.</p>') if tracker else ""
    empty_html = "" if n else '<p>No new matches this week.</p>'

    body_html = (
        '<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.45;color:#14201b;max-width:640px">'
        f'<h1 style="font-size:20px;margin:0 0 4px">Job matches · {html.escape(when)}</h1>'
        f'<p style="margin:0;color:{MUTED}">{html.escape(intro)}</p>{tracker_html}{empty_html}'
        f'{section_html("Strong fits", strong)}{section_html("Good fits", good)}{still_html}{missed_html}{note_html}'
        '</div>'
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")
    return msg


def send_smtp(msg, address, app_password):
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(address, app_password)
        s.send_message(msg)


def send_gmail_api(msg, client_id, client_secret, refresh_token):
    form = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=form), timeout=30) as r:
        token = json.load(r)["access_token"]
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    req = urllib.request.Request(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        data=json.dumps({"raw": raw}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def fail(message):
    print(f"::error title=Email not sent::{message}")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: send_job_email.py job-scan/latest.json [--preview]")
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    msg = build_message(data)

    if "--preview" in sys.argv:
        with open("preview.html", "w", encoding="utf-8") as f:
            f.write(msg.get_body(("html",)).get_content())
        print("Subject:", msg["Subject"])
        print(msg.get_body(("plain",)).get_content())
        return

    env = lambda k: (os.environ.get(k) or "").strip()
    names = ["EMAIL_TO", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"]
    present = [k for k in names if env(k)]
    # Names only, never values, so the run page shows which secrets the workflow received.
    print(f"::notice title=Secrets found::{', '.join(present) or 'none'}")

    sender = env("GMAIL_ADDRESS")
    to = env("EMAIL_TO") or sender
    if not to:
        fail("No recipient. Add a GMAIL_ADDRESS (or EMAIL_TO) repository secret.")
    msg["To"] = to
    if sender:
        msg["From"] = sender

    try:
        if env("GMAIL_APP_PASSWORD") and sender:
            send_smtp(msg, sender, env("GMAIL_APP_PASSWORD").replace(" ", ""))
            how = "Gmail app password"
        elif env("GMAIL_CLIENT_ID") and env("GMAIL_CLIENT_SECRET") and env("GMAIL_REFRESH_TOKEN"):
            send_gmail_api(msg, env("GMAIL_CLIENT_ID"), env("GMAIL_CLIENT_SECRET"), env("GMAIL_REFRESH_TOKEN"))
            how = "Gmail API"
        else:
            fail("No Gmail credentials found. Add GMAIL_ADDRESS + GMAIL_APP_PASSWORD, or "
                 "GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN, as repository secrets.")
    except smtplib.SMTPAuthenticationError as e:
        fail(f"Gmail rejected the sign-in ({e.smtp_code}). Check that GMAIL_ADDRESS is the account that "
             "created the app password and that GMAIL_APP_PASSWORD is the 16-character app password.")
    except Exception as e:  # report the error type and message on the run page
        fail(f"Sending failed: {type(e).__name__}: {e}")
    print(f"::notice title=Email sent::'{msg['Subject']}' to {to} via {how}")


if __name__ == "__main__":
    main()

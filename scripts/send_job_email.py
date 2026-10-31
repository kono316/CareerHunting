#!/usr/bin/env python3
"""Email the weekly job-scan results in job-scan/latest.json through Gmail.

Credentials come from environment variables (GitHub Actions secrets), never from files:
  Option A, Gmail app password:  GMAIL_ADDRESS + GMAIL_APP_PASSWORD
  Option B, Gmail API (OAuth):    GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET + GMAIL_REFRESH_TOKEN
                                  (+ GMAIL_ADDRESS if you want it shown as the sender)
Recipient: EMAIL_TO if set, otherwise GMAIL_ADDRESS.

Before sending, every job link is checked (scripts/check_links.py). Closed postings are left out
of the email, and the results are saved to job-scan/link-check.json for the Monday scan to read.

Usage:
  python scripts/send_job_email.py job-scan/latest.json               # check links, then send
  python scripts/send_job_email.py job-scan/latest.json --check-only  # check links, don't send
  python scripts/send_job_email.py job-scan/latest.json --preview     # write preview.html, don't check or send
"""
import base64
import html
import json
import os
import re
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_links import check_link, clean_url, is_official  # noqa: E402

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


def describe_credentials(address, password):
    """Facts about the secrets that help debugging without revealing them."""
    looks_gmail = re.fullmatch(r"[A-Za-z0-9._%+-]+@(gmail|googlemail)\.com", address or "", re.I)
    kind = "letters only" if password.isascii() and password.isalpha() else "includes characters other than letters"
    return (f"GMAIL_ADDRESS {'looks like a Gmail address' if looks_gmail else 'does not look like name@gmail.com'}; "
            f"GMAIL_APP_PASSWORD has {len(password)} characters ({kind}; a Google app password is 16 letters)")


def send_smtp(msg, address, app_password):
    """Try Gmail's SSL port, then STARTTLS on 587, then AUTH LOGIN, if the connection drops."""
    password = "".join(app_password.split())  # drops normal and non-breaking spaces copied from Google's page
    errors = []
    for port, mechanism in ((465, None), (587, None), (465, "LOGIN")):
        stage = "connect"
        try:
            ctx = ssl.create_default_context()
            if port == 465:
                s = smtplib.SMTP_SSL("smtp.gmail.com", port, context=ctx, timeout=30)
            else:
                s = smtplib.SMTP("smtp.gmail.com", port, timeout=30)
                s.ehlo()
                stage = "starttls"
                s.starttls(context=ctx)
            with s:
                s.ehlo()
                if mechanism:
                    s.esmtp_features["auth"] = mechanism
                stage = "login"
                s.login(address, password)
                stage = "send"
                s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError as e:
            raise RuntimeError(f"Gmail rejected the sign-in: {e.smtp_code} "
                               f"{e.smtp_error.decode(errors='replace')[:120]} | {describe_credentials(address, password)}")
        except (smtplib.SMTPServerDisconnected, OSError) as e:
            label = f"port {port}" + (f" {mechanism}" if mechanism else "")
            errors.append(f"{label} at {stage}: {type(e).__name__}: {e}")
    raise RuntimeError("; ".join(errors) + " | " + describe_credentials(address, password))


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
    message = " ".join(str(message).split())  # an annotation ends at the first line break
    print(f"::error title=Email not sent::{message}")
    sys.exit(1)


def check_and_filter(data, results_path):
    """Check every link, drop closed postings from the email, and save the results for the Monday scan."""
    results, closed, unofficial = [], [], []
    for key in ("strong", "good", "stillOpen"):
        kept = []
        for j in data.get(key) or []:
            j["url"] = clean_url(j.get("url"))
            if not is_official(j.get("url"), j.get("company")):
                status, reason = "unofficial", "not the employer's own job site"
            else:
                status, reason = check_link(safe_url(j.get("url")))
            results.append({"url": j.get("url"), "title": j.get("title"), "company": j.get("company"),
                            "status": status, "reason": reason})
            if status == "closed":
                closed.append(j)
            elif status == "unofficial":
                unofficial.append(j)
            else:
                kept.append(j)
        data[key] = kept
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump({"scanDate": data.get("date"), "checkedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "results": results}, f, indent=2, ensure_ascii=False)
    if closed:
        names = ", ".join(f"{j.get('title')} ({j.get('company')})" for j in closed)
        extra = f"Left out {len(closed)} posting{'s' if len(closed) != 1 else ''} that closed after the scan: {names}."
        data["note"] = f"{data.get('note') or ''} {extra}".strip()
    if unofficial:
        names = ", ".join(f"{j.get('title')} ({j.get('company')})" for j in unofficial)
        extra = (f"Left out {len(unofficial)} job{'s' if len(unofficial) != 1 else ''} without a link to the "
                 f"employer's own job site: {names}.")
        data["note"] = f"{data.get('note') or ''} {extra}".strip()
    counts = {s: sum(r["status"] == s for r in results) for s in ("open", "closed", "unknown", "unofficial")}
    print(f"::notice title=Link check::{counts['open']} open, {counts['closed']} closed, "
          f"{counts['unknown']} couldn't be checked, {counts['unofficial']} not on the employer's own site")
    for r in results:
        if r["status"] != "open":
            print(f"::warning title=Link {r['status']}::{r['title']} ({r['company']}): {r['reason']}")
    return data


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: send_job_email.py job-scan/latest.json [--preview] [--check-only] [--no-check]")
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    if "--no-check" not in sys.argv and "--preview" not in sys.argv:
        data = check_and_filter(data, os.path.join(os.path.dirname(sys.argv[1]) or ".", "link-check.json"))
    if "--check-only" in sys.argv:
        return
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
    except Exception as e:  # report the error type and message on the run page
        fail(f"Sending failed: {type(e).__name__}: {e}")
    print(f"::notice title=Email sent::'{msg['Subject']}' to {to} via {how}")


if __name__ == "__main__":
    main()

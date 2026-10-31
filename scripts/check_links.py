"""Check whether job-posting links still lead to an open posting.

check_link(url) returns (status, reason) where status is "open", "closed" or "unknown".
Workday, Greenhouse and Lever postings are checked through each site's own job data service,
because their posting pages load in the browser and can look fine to a plain download even
after the job has closed. Other sites get a page download that looks for redirects and
"no longer available" wording.
"""
import re
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

DEAD_PHRASES = (
    "no longer available", "no longer accepting applications", "no longer open",
    "this job has expired", "job has expired", "position has been filled", "job has been filled",
    "this job was removed", "job is closed", "posting is closed", "posting has closed",
    "page you are looking for doesn't exist", "page you are looking for does not exist",
    "job not found", "this job is no longer",
)


def _get(url, accept="text/html,application/json;q=0.9,*/*;q=0.8"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, r.geturl(), r.read(500_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read(20_000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, url, body


def _segments(path):
    return [urllib.parse.unquote(s) for s in path.split("/") if s]


def _workday(p):
    segs = _segments(p.path)
    if "job" not in segs:
        return None
    i = segs.index("job")
    before = [s for s in segs[:i] if not re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", s)]  # drop a locale like en-US
    if not before or i + 1 >= len(segs):
        return None
    tenant, site = p.netloc.split(".")[0], before[-1]
    rest = "/".join(urllib.parse.quote(s) for s in segs[i + 1:])
    code, _, body = _get(f"https://{p.netloc}/wday/cxs/{tenant}/{site}/job/{rest}", accept="application/json")
    if code == 200 and '"jobPostingInfo"' in body:
        return "open", "Workday says the posting is live"
    if code in (403, 404, 410) and '"errorCode"' in body:
        return "closed", "Workday no longer has this posting"
    return "unknown", f"Workday answered {code}"


def _greenhouse(p):
    segs = _segments(p.path)
    if len(segs) < 3 or segs[1] != "jobs" or not segs[2].isdigit():
        return None
    code, _, _ = _get(f"https://boards-api.greenhouse.io/v1/boards/{segs[0]}/jobs/{segs[2]}", accept="application/json")
    if code == 200:
        return "open", "Greenhouse says the posting is live"
    if code == 404:
        return "closed", "Greenhouse no longer has this posting"
    return "unknown", f"Greenhouse answered {code}"


def _lever(p):
    segs = _segments(p.path)
    if len(segs) < 2:
        return None
    code, _, _ = _get(f"https://api.lever.co/v0/postings/{segs[0]}/{segs[1]}", accept="application/json")
    if code == 200:
        return "open", "Lever says the posting is live"
    if code == 404:
        return "closed", "Lever no longer has this posting"
    return "unknown", f"Lever answered {code}"


def _posting_ids(url):
    """Tokens that identify a posting inside its URL: long numbers, long hex strings, requisition IDs."""
    path = urllib.parse.urlparse(url).path
    return set(re.findall(r"\d{5,}|[0-9A-Fa-f]{16,}|[A-Za-z]{1,4}-?\d{4,}", path))


def _generic(url):
    code, final, body = _get(url)
    if code in (404, 410):
        return "closed", f"the page returns {code}"
    if code >= 400:
        return "unknown", f"the site answered {code}"
    ids = _posting_ids(url)
    if ids and final != url and not any(i in final for i in ids):
        return "closed", "the link now redirects away from the posting"
    text = re.sub(r"<[^>]+>", " ", body).lower()
    for phrase in DEAD_PHRASES:
        if phrase in text:
            return "closed", f'the page says "{phrase}"'
    return "open", "the page loads"


def check_link(url):
    try:
        p = urllib.parse.urlparse(url)
        if p.scheme not in ("http", "https") or not p.netloc:
            return "closed", "not a web link"
        host = p.netloc.lower()
        result = None
        if host.endswith(".myworkdayjobs.com"):
            result = _workday(p)
        elif host in ("job-boards.greenhouse.io", "boards.greenhouse.io", "job-boards.eu.greenhouse.io"):
            result = _greenhouse(p)
        elif host == "jobs.lever.co":
            result = _lever(p)
        return result or _generic(url)
    except Exception as e:  # a network hiccup should never drop a job from the email
        return "unknown", f"check failed: {type(e).__name__}"

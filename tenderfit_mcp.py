#!/usr/bin/env python3
"""TenderFit MCP — MCP server for Prozorro, Ukrainian public procurement data for AI assistants.

Single file, Python 3.9+ standard library only, stdio transport (JSON-RPC 2.0, Model Context Protocol).
Uses only open public endpoints of Prozorro, no API key:
  prozorro.gov.ua/api/search      — tender and product search
  public-api.prozorro.gov.ua      — full tender data (documents, Q&A, awards, contracts)
  risks.prozorro.gov.ua           — official State Audit Service (DASU) risk indicators
  audit-api.prozorro.gov.ua       — DASU monitorings

Run:  python3 tenderfit_mcp.py
Made by TenderFit (https://t.me/tenderfit). Independent project, not affiliated with SE "Prozorro".
MIT License.
"""
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

VERSION = "0.1.0"
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
UA = {"User-Agent": "curl/8.5.0 tenderfit-mcp/" + VERSION, "Accept": "application/json"}
GAP = {"prozorro.gov.ua": 0.8, "public-api.prozorro.gov.ua": 0.15, "risks.prozorro.gov.ua": 0.3,
       "audit-api.prozorro.gov.ua": 0.15}           # polite per-host pause, prozorro.gov.ua allows ~60 req/min
_last, _lock = {}, threading.Lock()
TID_RE = re.compile(r"^UA-\d{4}-\d{2}-\d{2}-\d{6}-[a-z]$", re.I)
HEX_RE = re.compile(r"^[0-9a-f]{32}$")
_hex_cache = {}


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- HTTP
def http(url, body=None, tries=5, timeout=60):
    host = urllib.parse.urlparse(url).hostname
    hdr = dict(UA)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdr["Content-Type"] = "application/json"
    for i in range(tries):
        with _lock:
            wait = _last.get(host, 0) + GAP.get(host, 0) - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[host] = time.time()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data, hdr), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if i == tries - 1 or e.code in (400, 401, 403):
                raise ToolError(f"Prozorro returned HTTP {e.code} for {host}")
            time.sleep((10 if e.code == 429 else 2) * (i + 1))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if i == tries - 1:
                raise ToolError(f"{host} is not reachable: {e}")
            time.sleep(2 * (i + 1))


def hexid(tender_id):
    """UA-2026-10-19-000516-a or 32-char hex -> hex id used by the public API."""
    tender_id = (tender_id or "").strip()
    if HEX_RE.match(tender_id):
        return tender_id
    if not TID_RE.match(tender_id):
        raise ToolError("tender_id must look like UA-2026-10-19-000516-a or a 32-character hex id")
    if tender_id not in _hex_cache:
        r = http(f"https://prozorro.gov.ua/api/tenders/{tender_id.upper()[:-1] + tender_id[-1].lower()}/summary")
        if not r or not r.get("id"):
            raise ToolError(f"Tender {tender_id} not found")
        _hex_cache[tender_id] = r["id"]
    return _hex_cache[tender_id]


def load_tender(tender_id):
    r = http("https://public-api.prozorro.gov.ua/api/2.5/tenders/" + hexid(tender_id))
    if not r:
        raise ToolError(f"Tender {tender_id} not found")
    return r["data"]


def cut(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def money(v):
    return {"amount": v.get("amount"), "currency": v.get("currency"), "vat_included": v.get("valueAddedTaxIncluded")} if v else None


def edr(org):
    return ((org or {}).get("identifier") or {}).get("id")


# ---------------------------------------------------------------- tools
def search_tenders(text=None, cpv=None, buyer_edrpou=None, tenderer_edrpou=None, status=None,
                   procedure_type=None, date_from=None, date_to=None, page=1):
    body = {}
    if text:
        body["text"] = text
    if cpv:
        body["cpv"] = [cpv] if isinstance(cpv, str) else cpv
    if buyer_edrpou:
        body["buyer"] = [str(buyer_edrpou)]
    if tenderer_edrpou:
        body["tenderer"] = [str(tenderer_edrpou)]
    if status:
        body["status"] = [status] if isinstance(status, str) else status
    if procedure_type:
        body["proc_type"] = [procedure_type] if isinstance(procedure_type, str) else procedure_type
    if date_from or date_to:
        body["date"] = {"notice": {k: v for k, v in (("start", date_from), ("end", date_to)) if v}}
    r = http(f"https://prozorro.gov.ua/api/search/tenders?page={int(page or 1)}", body) or {}
    items = [{"tender_id": x.get("tenderID"), "title": x.get("title"), "status": x.get("status"),
              "buyer": (x.get("procuringEntity") or {}).get("name"),
              "locality": ((x.get("procuringEntity") or {}).get("address") or {}).get("locality"),
              "value": money(x.get("value")),
              "bids_until": (x.get("tenderPeriod") or {}).get("endDate"),
              "questions_until": (x.get("enquiryPeriod") or {}).get("endDate"),
              "url": f"https://prozorro.gov.ua/tender/{x.get('tenderID')}"} for x in r.get("data", [])]
    return {"total": r.get("total", 0), "page": r.get("page", page), "per_page": r.get("per_page", 20),
            "note": "Without text results are sorted by date, with text by relevance. Max 10 000 results per query.",
            "items": items}


def get_tender(tender_id, max_documents=40, max_questions=15):
    t = load_tender(tender_id)
    pe = t.get("procuringEntity") or {}
    lots = {l["id"]: l for l in t.get("lots", []) or []}
    out = {
        "tender_id": t.get("tenderID"), "hex_id": t.get("id"), "url": f"https://prozorro.gov.ua/tender/{t.get('tenderID')}",
        "title": t.get("title"), "status": t.get("status"), "procedure_type": t.get("procurementMethodType"),
        "buyer": {"name": pe.get("name"), "edrpou": edr(pe), "kind": pe.get("kind"),
                  "locality": (pe.get("address") or {}).get("locality"), "region": (pe.get("address") or {}).get("region"),
                  "contact": {k: (pe.get("contactPoint") or {}).get(k) for k in ("name", "email", "telephone")}},
        "value": money(t.get("value")),
        "questions_until": (t.get("enquiryPeriod") or {}).get("endDate"),
        "bids_until": (t.get("tenderPeriod") or {}).get("endDate"),
        "guarantee": money(t.get("guarantee")),
        "lots": [{"id": l["id"], "title": l.get("title"), "status": l.get("status"), "value": money(l.get("value"))}
                 for l in lots.values()],
        "items": [{"description": cut(i.get("description"), 300), "quantity": i.get("quantity"),
                   "unit": (i.get("unit") or {}).get("name"), "cpv": (i.get("classification") or {}).get("id"),
                   "delivery_until": (i.get("deliveryDate") or {}).get("endDate"),
                   "delivery_locality": (i.get("deliveryAddress") or {}).get("locality")}
                  for i in (t.get("items") or [])[:50]],
        "payment_terms": [{"event": m.get("code"), "days": m.get("duration", {}).get("days"),
                           "day_type": m.get("duration", {}).get("type"), "percentage": m.get("percentage")}
                          for m in t.get("milestones", []) or []],
        "criteria": [{"title": cut(c.get("title"), 200), "source": c.get("source"),
                      "classification": (c.get("classification") or {}).get("id")} for c in t.get("criteria", []) or []],
        "documents": [{"title": d.get("title"), "type": d.get("documentType"), "format": d.get("format"),
                       "published": d.get("datePublished"), "url": d.get("url")}
                      for d in (t.get("documents") or [])[-int(max_documents):]],
        "questions": {"count": len(t.get("questions") or []),
                      "items": [{"date": q.get("date"), "title": cut(q.get("title"), 150),
                                 "question": cut(q.get("description"), 600), "answer": cut(q.get("answer"), 600)}
                                for q in (t.get("questions") or [])[-int(max_questions):]]},
        "complaints": len(t.get("complaints") or []),
        "bids": len(t.get("bids") or []),
        "awards": [{"status": a.get("status"), "date": a.get("date"),
                    "lot": (lots.get(a.get("lotID")) or {}).get("title"),
                    "supplier": (a.get("suppliers") or [{}])[0].get("name"),
                    "supplier_edrpou": edr((a.get("suppliers") or [{}])[0]), "value": money(a.get("value")),
                    "reason_title": cut(a.get("title"), 300) if a.get("status") == "unsuccessful" else None,
                    "reason": cut(a.get("description"), 800) if a.get("status") == "unsuccessful" else None}
                   for a in t.get("awards", []) or []],
        "contracts": [{"status": c.get("status"), "value": money(c.get("value")), "signed": c.get("dateSigned")}
                      for c in t.get("contracts", []) or []],
    }
    return out


RISK_SHORT = {
    "sas24-3-5": "rejected 2+ bidders without the '24 hours' correction mechanism",
    "sas24-3-2": "rejected 2+ bidders other than the winner (goods/services)",
    "sas24-3-2-1": "rejected 2+ bidders other than the winner (works)",
    "sas24-3-15": "rejected 2+ bidders while a complaint was pending at AMCU",
    "sas24-3-1": "did not execute the AMCU (appeal body) decision on time",
    "sas24-3-9": "re-selected the same winner after an AMCU decision",
    "sas24-3-10": "did not reject a winner who failed to publish documents",
    "sas24-3-11-1": "signed a contract outside Prozorro after cancelling open tender",
    "sas24-3-11-2": "signed a contract outside Prozorro during an appeal",
    "sas24-3-13": "unjustified '24 hours' request in a simplified procurement",
    "sas24-3-4": "changed contract price more often than once per 90 days",
    "sas24-3-7": "very short execution period of a works contract",
    "ari-1-1": "3+ amendments to the contract",
    "ari-1-2": "2+ amendments 'quality improvement'",
}


def _found(item):
    return [k for k, v in (item.get("risks") or {}).items() if any(r.get("indicator") == "risk_found" for r in v)]


def tender_risks(tender_id):
    h = hexid(tender_id)
    r = http(f"https://risks.prozorro.gov.ua/api/risks/{h}")
    if not r:
        return {"tender_id": tender_id, "assessed": False,
                "note": "The risk service has not assessed this tender (yet). Most indicators apply after awards."}
    risks = r.get("risks") or {}
    found = _found(r)
    return {"tender_id": r.get("tenderID") or tender_id, "assessed": True, "date_assessed": r.get("dateAssessed"),
            "has_risks": r.get("has_risks"), "checked_indicators": len(risks),
            "found": [{"id": k, "short": RISK_SHORT.get(k), "name_uk": risks[k][0].get("name"),
                       "legal_basis_uk": cut(risks[k][0].get("legitimateness"), 600)} for k in found],
            "source": "https://risks.prozorro.gov.ua (State Audit Service of Ukraine risk indicators)"}


def buyer_risks(edrpou, months=24):
    edrpou = re.sub(r"\D", "", str(edrpou or ""))
    if not 6 <= len(edrpou) <= 10:
        raise ToolError("edrpou must be the buyer's EDRPOU code (8 digits)")
    items, total = [], 0
    while len(items) < 1000:
        r = http(f"https://risks.prozorro.gov.ua/api/risks?edrpou={edrpou}&limit=100&skip={len(items)}"
                 "&sort=dateAssessed&order=desc") or {}
        total = r.get("count", 0)
        items += r.get("items", [])
        if not r.get("items") or len(items) >= total:
            break
    since = time.strftime("%Y-%m-%d", time.gmtime(time.time() - months * 30.4 * 86400))
    items = [x for x in items if (x.get("dateCreated") or "")[:10] >= since]
    by, ex, names = Counter(), {}, {}
    for x in items:
        for k in _found(x):
            by[k] += 1
            ex.setdefault(k, []).append(x.get("tenderID"))
            names.setdefault(k, x["risks"][k][0].get("name"))
    buyer = (items[0].get("procuringEntity") or {}).get("name") if items else None
    return {"edrpou": edrpou, "buyer": buyer, "months": months, "flagged_procedures": len(items),
            "note": "Only procedures with at least one triggered indicator are counted (the service lists only those).",
            "indicators": [{"id": k, "count": n, "short": RISK_SHORT.get(k), "name_uk": names.get(k),
                            "examples": ex[k][:3]} for k, n in by.most_common()],
            "source": "https://risks.prozorro.gov.ua"}


def tender_monitorings(tender_id):
    h = hexid(tender_id)
    r = http(f"https://audit-api.prozorro.gov.ua/api/2.5/tenders/{h}/monitorings?opt_fields=status,reasons,"
             "procuringStages,monitoringPeriod,conclusion,monitoring_id,dateModified") or {}
    ms = r.get("data", [])
    return {"tender_id": tender_id, "count": len(ms),
            "monitorings": [{"monitoring_id": m.get("monitoring_id"), "status": m.get("status"),
                             "reasons": m.get("reasons"), "stages": m.get("procuringStages"),
                             "violation": (m.get("conclusion") or {}).get("violationOccurred"),
                             "violation_types": (m.get("conclusion") or {}).get("violationType"),
                             "conclusion": cut((m.get("conclusion") or {}).get("auditFinding"), 800),
                             "modified": m.get("dateModified")} for m in ms],
            "source": "https://audit-api.prozorro.gov.ua"}


COMPETITIVE = ("aboveThreshold", "aboveThresholdUA", "aboveThresholdEU", "belowThreshold")


def buyer_rejections(edrpou, limit=20):
    """Why does this buyer reject bids? Looks at the buyer's latest competitive procedures with decisions."""
    edrpou = re.sub(r"\D", "", str(edrpou or ""))
    limit = max(1, min(int(limit or 20), 60))
    ids = []
    for page in range(1, 4):
        r = http(f"https://prozorro.gov.ua/api/search/tenders?page={page}",
                 {"buyer": [edrpou], "status": ["complete", "unsuccessful", "active.awarded", "active.qualification"],
                  "proc_type": list(COMPETITIVE)}) or {}
        ids += [x["tenderID"] for x in r.get("data", [])]
        if len(ids) >= limit or not r.get("data"):
            break
    ids = ids[:limit]
    decided = rejected = with_rej = 0
    titles, examples, buyer = Counter(), [], None
    for tid in ids:
        try:
            t = load_tender(tid)
        except ToolError:
            continue
        buyer = buyer or (t.get("procuringEntity") or {}).get("name")
        aw = [a for a in t.get("awards", []) or [] if a.get("status") in ("active", "unsuccessful", "cancelled")]
        rej = [a for a in aw if a.get("status") == "unsuccessful"]
        decided += len([a for a in aw if a.get("status") in ("active", "unsuccessful")])
        rejected += len(rej)
        with_rej += bool(rej)
        for a in rej:
            titles[cut(a.get("title"), 160)] += 1
            if len(examples) < 8 and a.get("description"):
                examples.append({"tender_id": tid, "supplier": (a.get("suppliers") or [{}])[0].get("name"),
                                 "reason": cut(a.get("description"), 500)})
    return {"edrpou": edrpou, "buyer": buyer, "procedures_checked": len(ids), "decisions": decided,
            "rejections": rejected, "procedures_with_rejections": with_rej,
            "rejection_rate": round(rejected / decided, 3) if decided else None,
            "top_legal_grounds": [{"ground": k, "count": v} for k, v in titles.most_common(5)],
            "examples": examples}


def search_localized_products(text, page=1, details=5):
    """Prozorro product catalogue incl. the localization list (Resolution 861: share of Ukrainian content)."""
    r = http(f"https://prozorro.gov.ua/api/search/products?page={int(page or 1)}", {"text": text}) or {}
    items = []
    for i, x in enumerate(r.get("data", [])):
        it = {"product_id": x.get("id"), "title": cut(x.get("title"), 200), "status": x.get("status"),
              "cpv": (x.get("classification") or {}).get("id"), "created": x.get("dateCreated")}
        if i < int(details or 0):
            d = http(f"https://prozorro.gov.ua/api/products/{x.get('id')}") or {}
            d = d.get("data", d)
            it.update({"localization_percent": d.get("localization"), "expires": d.get("expirationDate") or None,
                       "vendor": (d.get("vendor") or {}).get("name"),
                       "vendor_edrpou": (d.get("vendor") or {}).get("id"),
                       "manufacturer": (d.get("manufacturer") or {}).get("name") if isinstance(d.get("manufacturer"), dict) else None,
                       "url": f"https://prozorro.gov.ua/uk/product/{x.get('id')}"})
        items.append(it)
    return {"total": r.get("total", 0), "page": r.get("page", page), "items": items}


S = {"type": "string"}
TOOLS = [
    {"name": "search_tenders", "fn": search_tenders,
     "description": "Search Ukrainian public tenders on Prozorro by text, CPV code, buyer or bidder EDRPOU, status, "
                    "procedure type and announcement date. Returns 20 results per page.",
     "inputSchema": {"type": "object", "properties": {
         "text": {**S, "description": "Free text, Ukrainian works best, e.g. 'дизельний генератор'"},
         "cpv": {"type": "array", "items": S, "description": "CPV codes like '31120000-3'"},
         "buyer_edrpou": {**S, "description": "Buyer (procuring entity) EDRPOU code"},
         "tenderer_edrpou": {**S, "description": "Bidder EDRPOU code"},
         "status": {"type": "array", "items": {"type": "string", "enum": [
             "active.enquiries", "active.tendering", "active.qualification", "active.awarded",
             "complete", "unsuccessful", "cancelled"]}},
         "procedure_type": {"type": "array", "items": S,
                            "description": "e.g. aboveThreshold, aboveThresholdUA, belowThreshold, reporting"},
         "date_from": {**S, "description": "Announcement date from, YYYY-MM-DD"},
         "date_to": {**S, "description": "Announcement date to, YYYY-MM-DD"},
         "page": {"type": "integer", "minimum": 1}}}},
    {"name": "get_tender", "fn": get_tender,
     "description": "Full tender card: buyer and contact, value, deadlines, lots, items, payment terms, criteria, "
                    "documents with download links, questions and answers, awards with rejection reasons, contracts.",
     "inputSchema": {"type": "object", "required": ["tender_id"], "properties": {
         "tender_id": {**S, "description": "UA-2026-10-19-000516-a or hex id"},
         "max_documents": {"type": "integer", "minimum": 1, "maximum": 200},
         "max_questions": {"type": "integer", "minimum": 0, "maximum": 100}}}},
    {"name": "tender_risks", "fn": tender_risks,
     "description": "Official State Audit Service (DASU) risk indicators triggered for one tender.",
     "inputSchema": {"type": "object", "required": ["tender_id"], "properties": {"tender_id": S}}},
    {"name": "buyer_risks", "fn": buyer_risks,
     "description": "How often a buyer triggers DASU risk indicators: rejecting several bidders, ignoring appeal "
                    "decisions, contract amendments. Use before bidding to judge a buyer.",
     "inputSchema": {"type": "object", "required": ["edrpou"], "properties": {
         "edrpou": S, "months": {"type": "integer", "minimum": 1, "maximum": 72}}}},
    {"name": "tender_monitorings", "fn": tender_monitorings,
     "description": "DASU monitorings of a tender: status, reasons, whether a violation was found, conclusion.",
     "inputSchema": {"type": "object", "required": ["tender_id"], "properties": {"tender_id": S}}},
    {"name": "buyer_rejections", "fn": buyer_rejections,
     "description": "Why a buyer rejects bids: rejection rate, top legal grounds and real wording from the buyer's "
                    "latest finished procedures. Slow: about 1–2 seconds per procedure.",
     "inputSchema": {"type": "object", "required": ["edrpou"], "properties": {
         "edrpou": S, "limit": {"type": "integer", "minimum": 1, "maximum": 60}}}},
    {"name": "search_localized_products", "fn": search_localized_products,
     "description": "Search the Prozorro product catalogue, including the localization list (Ukrainian content "
                    "share required in many tenders). Details (localization %, vendor, expiry) for the first N.",
     "inputSchema": {"type": "object", "required": ["text"], "properties": {
         "text": S, "page": {"type": "integer", "minimum": 1},
         "details": {"type": "integer", "minimum": 0, "maximum": 20}}}},
]
BY_NAME = {t["name"]: t for t in TOOLS}


# ---------------------------------------------------------------- MCP over stdio
_out = threading.Lock()


def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg["error" if error else "result"] = error or result
    with _out:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def handle(msg):
    method, id_, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if id_ is None:                                   # notification (e.g. notifications/initialized)
        return
    if method == "initialize":
        want = params.get("protocolVersion")
        reply(id_, {"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0],
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "tenderfit-mcp", "version": VERSION},
                    "instructions": "Ukrainian public procurement (Prozorro) data. Tender ids look like "
                                    "UA-2026-10-19-000516-a; buyers are identified by EDRPOU. Texts are in Ukrainian."})
    elif method == "ping":
        reply(id_, {})
    elif method == "tools/list":
        reply(id_, {"tools": [{k: t[k] for k in ("name", "description", "inputSchema")} for t in TOOLS]})
    elif method == "tools/call":
        tool = BY_NAME.get(params.get("name"))
        if not tool:
            return reply(id_, error={"code": -32602, "message": f"Unknown tool: {params.get('name')}"})
        try:
            res = tool["fn"](**(params.get("arguments") or {}))
            reply(id_, {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}],
                        "isError": False})
        except TypeError as e:
            reply(id_, {"content": [{"type": "text", "text": f"Bad arguments: {e}"}], "isError": True})
        except ToolError as e:
            reply(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:                       # never kill the session because of one call
            reply(id_, {"content": [{"type": "text", "text": f"Internal error: {e!r}"}], "isError": True})
    else:
        reply(id_, error={"code": -32601, "message": f"Method not found: {method}"})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply(None, error={"code": -32700, "message": "Parse error"})
            continue
        for m in (msg if isinstance(msg, list) else [msg]):
            if not isinstance(m, dict):
                continue
            if m.get("method") == "tools/call":      # tools can take seconds: own thread, ping/list stay responsive
                threading.Thread(target=handle, args=(m,), daemon=True).start()
            else:
                handle(m)
    # stdin closed: let running tool calls finish
    for th in threading.enumerate():
        if th is not threading.current_thread() and th.daemon:
            th.join(timeout=120)


if __name__ == "__main__":
    main()

"""Push mode: ServiceNow calls POST /suggest or /kb-draft with {"sys_id": "..."}; Jarvis answers 202 and works in the background."""
import hmac
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SYS_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_BODY = 10_000


def parse_sys_id(body):
    """Only the sys_id is taken from the caller; the incident itself is re-read from ServiceNow."""
    try:
        sys_id = json.loads(body).get("sys_id")
    except (ValueError, AttributeError):
        return None
    return sys_id if isinstance(sys_id, str) and SYS_ID.match(sys_id) else None


def make_server(port, token, routes, host="127.0.0.1", api=None):
    """routes: path -> work(sys_id), run in the background (202). api: path -> fn(dict) -> (status, dict), answered
    synchronously as JSON; each fn validates its own input."""
    api = api or {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                return self.send_error(413)
            body = self.rfile.read(length)  # read before any error reply, or Windows clients see a reset connection
            work, fn = routes.get(self.path), api.get(self.path)
            if not (work or fn):
                return self.send_error(404)
            if not hmac.compare_digest(self.headers.get("X-Jarvis-Token", ""), token):
                return self.send_error(401)
            if fn:
                try:
                    data = json.loads(body)
                except ValueError:
                    data = None
                status, out = fn(data) if isinstance(data, dict) else (400, {"error": "body must be a JSON object"})
                payload = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                return self.wfile.write(payload)
            sys_id = parse_sys_id(body)
            if not sys_id:
                return self.send_error(400, "body must be {\"sys_id\": \"<32 hex chars>\"}")
            threading.Thread(target=work, args=(sys_id,), daemon=True).start()
            self.send_response(202)
            self.end_headers()

    return ThreadingHTTPServer((host, port), Handler)


REGISTERED = {"host": None}


def register_tunnel(snow, token, metrics_url, tries=60):
    """Read the quick tunnel's public URL from cloudflared and point ServiceNow at it. Called at startup and on every
    background loop: a quick tunnel gets a new URL when cloudflared restarts, and ServiceNow must follow."""
    import requests
    from seed.install_snow import install
    for _ in range(tries):
        try:
            host = requests.get(f"{metrics_url}/quicktunnel", timeout=5).json().get("hostname")
        except (requests.RequestException, ValueError):
            host = None
        if host and host == REGISTERED["host"]:
            return
        if host:
            print(f"Tunnel: https://{host}")
            install(snow, f"https://{host}", token)
            REGISTERED["host"] = host
            return
        time.sleep(2)
    print("Tunnel URL not available: ServiceNow still points to the previous endpoint")


def main():
    from jarvis.config import llm_from_env, snow_from_env
    from jarvis.main import handle, handle_approve, handle_diagnose, handle_feedback, handle_implement, handle_resolved

    token = os.environ["JARVIS_TOKEN"]
    if len(token) < 16:
        raise SystemExit("JARVIS_TOKEN must be at least 16 characters.")
    snow = snow_from_env()
    llm, model = llm_from_env()

    def job(fn, table="incident"):
        def work(sys_id):
            try:
                record = snow.get(table, sys_id)  # always re-read: the request only names the record
                if record:
                    fn(record, snow, llm, model)
            except Exception as e:  # log and keep serving; ServiceNow is not waiting for the result
                print(f"{sys_id}: failed: {e}")
        return work

    if snow.semantic:  # embed KB and history now, not on the first ticket
        print("Building the semantic index...")
        snow.search_kb("warm up"), snow.kb_candidates("warm up"), snow.similar_resolved("warm up")
    port, host = int(os.getenv("JARVIS_PORT", "8787")), os.getenv("JARVIS_HOST", "127.0.0.1")
    from jarvis import selfservice
    api = {"/ask": lambda d: selfservice.ask(d, snow, llm, model), "/ask-outcome": lambda d: selfservice.outcome(d, snow)}
    server = make_server(port, token, {"/suggest": job(handle), "/kb-draft": job(handle_resolved),
                                       "/approve": job(handle_approve), "/diagnose": job(handle_diagnose),
                                       "/implement": job(handle_implement, "change_request"),
                                       "/feedback": job(handle_feedback)}, host, api)
    print(f"Jarvis listening on http://{host}:{port} (/suggest, /kb-draft, /approve, /diagnose, /implement, /feedback, /ask, /ask-outcome)")
    threading.Thread(target=background, args=(snow, token), daemon=True).start()
    server.serve_forever()


def background(snow, token):
    """After the socket is open: register the tunnel (docker compose), then keep the knowledge base in sync."""
    if os.getenv("JARVIS_TUNNEL_METRICS"):
        register_tunnel(snow, token, os.environ["JARVIS_TUNNEL_METRICS"])
    docs = bool(snow.knowledge and (os.getenv("DOCS_REPO") or os.getenv("DOCS_DIR")))
    if not docs:
        print("knowledge: no DATABASE_URL or docs source (DOCS_REPO / DOCS_DIR): answering from the ServiceNow KB")
    from jarvis.config import KB_TITLE
    from jarvis.knowledge import sync
    force = True  # first run and after a failure: re-read even a known commit so nothing stays unpublished
    while True:
        if docs:
            try:
                sync(snow, snow.knowledge, KB_TITLE, force)
                force = False
            except Exception as e:  # GitHub or ServiceNow down: keep the last good knowledge base and retry
                print(f"knowledge: sync failed, retrying: {e}")
                force = True
        weekly_report(snow)
        if os.getenv("JARVIS_TUNNEL_METRICS"):
            try:
                register_tunnel(snow, token, os.environ["JARVIS_TUNNEL_METRICS"], tries=1)
            except Exception as e:  # ServiceNow unreachable: keep the old registration, retry next loop
                print(f"tunnel: re-registration failed: {e}")
        time.sleep(int(os.getenv("DOCS_POLL_SECONDS", "300")))


def weekly_report(snow, now=None):
    """Monday from 08:00 UTC: post the weekly report once per ISO week (the week posted is kept in the database)."""
    import datetime
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if not snow.db or now.weekday() != 0 or now.hour < 8:
        return
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    row = snow.db.execute("SELECT value FROM knowledge_state WHERE key = 'report_week'").fetchone()
    if row and row[0] == week:
        return
    from jarvis import report
    try:
        report.post(report.build(snow.db, today=now.date()))
        snow.db.execute("INSERT INTO knowledge_state (key, value) VALUES ('report_week', %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (week,))
        print(f"report: weekly report {week} posted")
    except Exception as e:  # Slack down: try again at the next loop
        print(f"report: not posted: {e}")


if __name__ == "__main__":
    main()

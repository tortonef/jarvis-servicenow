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


def make_server(port, token, routes, host="127.0.0.1"):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                return self.send_error(413)
            body = self.rfile.read(length)  # read before any error reply, or Windows clients see a reset connection
            work = routes.get(self.path)
            if not work:
                return self.send_error(404)
            if not hmac.compare_digest(self.headers.get("X-Jarvis-Token", ""), token):
                return self.send_error(401)
            sys_id = parse_sys_id(body)
            if not sys_id:
                return self.send_error(400, "body must be {\"sys_id\": \"<32 hex chars>\"}")
            threading.Thread(target=work, args=(sys_id,), daemon=True).start()
            self.send_response(202)
            self.end_headers()

    return ThreadingHTTPServer((host, port), Handler)


def register_tunnel(snow, token, metrics_url, tries=60):
    """Read the quick tunnel's public URL from cloudflared and point ServiceNow at it (URL changes on every restart)."""
    import requests
    from seed.install_snow import install
    for _ in range(tries):
        try:
            host = requests.get(f"{metrics_url}/quicktunnel", timeout=5).json().get("hostname")
        except (requests.RequestException, ValueError):
            host = None
        if host:
            print(f"Tunnel: https://{host}")
            return install(snow, f"https://{host}", token)
        time.sleep(2)
    print("Tunnel URL not available: ServiceNow still points to the previous endpoint")


def main():
    from jarvis.config import llm_from_env, snow_from_env
    from jarvis.main import handle, handle_remediation, handle_resolved

    token = os.environ["JARVIS_TOKEN"]
    if len(token) < 16:
        raise SystemExit("JARVIS_TOKEN must be at least 16 characters.")
    snow = snow_from_env()
    llm, model = llm_from_env()

    def job(fn):
        def work(sys_id):
            try:
                inc = snow.get_incident(sys_id)
                if inc:
                    fn(inc, snow, llm, model)
            except Exception as e:  # log and keep serving; ServiceNow is not waiting for the result
                print(f"{sys_id}: failed: {e}")
        return work

    if snow.semantic:  # embed KB and history now, not on the first ticket
        print("Building the semantic index...")
        snow.search_kb("warm up"), snow.kb_candidates("warm up"), snow.similar_resolved("warm up")
    port, host = int(os.getenv("JARVIS_PORT", "8787")), os.getenv("JARVIS_HOST", "127.0.0.1")
    server = make_server(port, token, {"/suggest": job(handle), "/kb-draft": job(handle_resolved),
                                       "/remediate": job(handle_remediation)}, host)
    print(f"Jarvis listening on http://{host}:{port} (/suggest, /kb-draft, /remediate)")
    if os.getenv("JARVIS_TUNNEL_METRICS"):  # docker compose: register the tunnel once the socket is open
        threading.Thread(target=register_tunnel, args=(snow, token, os.environ["JARVIS_TUNNEL_METRICS"]), daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()

"""Push mode: ServiceNow calls POST /suggest {"sys_id": "..."}; Jarvis answers 202 and posts the work note in the background."""
import hmac
import json
import os
import re
import threading
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


def make_server(port, token, work):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/suggest":
                return self.send_error(404)
            if not hmac.compare_digest(self.headers.get("X-Jarvis-Token", ""), token):
                return self.send_error(401)
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self.send_error(413)
            sys_id = parse_sys_id(self.rfile.read(length))
            if not sys_id:
                return self.send_error(400, "body must be {\"sys_id\": \"<32 hex chars>\"}")
            threading.Thread(target=work, args=(sys_id,), daemon=True).start()
            self.send_response(202)
            self.end_headers()

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    from jarvis.config import llm_from_env, snow_from_env
    from jarvis.main import handle

    token = os.environ["JARVIS_TOKEN"]
    if len(token) < 16:
        raise SystemExit("JARVIS_TOKEN must be at least 16 characters.")
    snow = snow_from_env()
    llm, model = llm_from_env()

    def work(sys_id):
        try:
            inc = snow.get_incident(sys_id)
            if inc:
                handle(inc, snow, llm, model)
        except Exception as e:  # log and keep serving; ServiceNow is not waiting for the result
            print(f"{sys_id}: failed: {e}")

    port = int(os.getenv("JARVIS_PORT", "8787"))
    print(f"Jarvis listening on http://127.0.0.1:{port}/suggest")
    make_server(port, token, work).serve_forever()


if __name__ == "__main__":
    main()

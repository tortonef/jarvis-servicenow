"""HTTP layer of push mode, on a real local server with a fake worker."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from jarvis.server import make_server

TOKEN = "t" * 32
SYS_ID = "1fd540d31b9c1310b3d3ea46624bcb0a"


class TestServer(unittest.TestCase):
    def setUp(self):
        self.calls, self.done = [], threading.Event()
        self.server = make_server(0, TOKEN, {"/suggest": lambda s: (self.calls.append(s), self.done.set())},
                                  api={"/ask": lambda d: (200, {"echo": d.get("question")})})
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def post(self, body, token=TOKEN, path="/suggest"):
        req = urllib.request.Request(self.url + path, data=body.encode(), method="POST",
                                     headers={"X-Jarvis-Token": token, "Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code

    def test_valid_request_is_accepted_and_processed(self):
        self.assertEqual(self.post(json.dumps({"sys_id": SYS_ID})), 202)
        self.assertTrue(self.done.wait(5))
        self.assertEqual(self.calls, [SYS_ID])

    def test_api_routes_answer_json_synchronously(self):
        req = urllib.request.Request(self.url + "/ask", data=json.dumps({"question": "hi"}).encode(), method="POST",
                                     headers={"X-Jarvis-Token": TOKEN})
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertEqual((r.status, json.loads(r.read())), (200, {"echo": "hi"}))
        self.assertEqual(self.post("[1]", path="/ask"), 400)                 # must be a JSON object
        self.assertEqual(self.post('{"question": "hi"}', token="no", path="/ask"), 401)

    def test_rejects_bad_token_body_and_path(self):
        self.assertEqual(self.post(json.dumps({"sys_id": SYS_ID}), token="wrong"), 401)
        self.assertEqual(self.post(json.dumps({"sys_id": "x^ORactive=true"})), 400)
        self.assertEqual(self.post("not json"), 400)
        self.assertEqual(self.post("[1]"), 400)
        self.assertEqual(self.post(json.dumps({"sys_id": SYS_ID}), path="/other"), 404)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()

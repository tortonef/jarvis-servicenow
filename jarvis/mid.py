"""Call fixed MID Server functions through ServiceNow's ECC queue (JavascriptProbe) and wait for the answer.

Jarvis never reaches the lab directly: it writes an output record to the ECC queue, the MID Server picks it up
(outbound only), runs a MID Script Include on-prem and writes the result back as an input record.
"""
import json
import os
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

# The only code that can reach the MID: named calls to MID Script Includes. Arguments travel as probe parameters.
CALLS = {
    "lockout_status": "new JarvisLdap().lockoutStatus(probe.getParameter('account'))",
}


def payload(call, params):
    parts = [f'<parameter name="script" value={quoteattr(CALLS[call])}/>']
    parts += [f"<parameter name={quoteattr(k)} value={quoteattr(str(v))}/>" for k, v in params.items()]
    return "<parameters>" + "".join(parts) + "</parameters>"


def parse_result(xml_text):
    """The probe's return value, decoded from JSON, from an ECC input payload."""
    root = ET.fromstring(xml_text)
    if root.get("error"):
        raise RuntimeError(f"MID probe error: {root.get('error')}")
    node = root.find(".//result/output")
    if node is None:
        node = root.find(".//result")
    text = (node.text or "").strip() if node is not None else ""
    if not text:
        raise RuntimeError(f"empty MID result: {xml_text[:300]}")
    return json.loads(text)


def run(snow, call, params, timeout=60, poll=2):
    if call not in CALLS:
        raise ValueError(f"unknown MID call: {call}")
    mid = os.getenv("MID_SERVER", "helios-mid")
    out = snow.create("ecc_queue", {"agent": f"mid.server.{mid}", "topic": "JavascriptProbe", "name": f"Jarvis: {call}",
                                    "queue": "output", "state": "ready", "payload": payload(call, params)})
    deadline = time.time() + timeout
    while time.time() < deadline:
        answer = snow.first("ecc_queue", f"queue=input^response_to={out['sys_id']}")
        if answer:
            return parse_result(answer["payload"])
        time.sleep(poll)
    raise TimeoutError(f"MID Server {mid} did not answer {call} within {timeout}s (is it up and validated?)")

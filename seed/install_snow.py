"""Install the ServiceNow side of push mode: system properties, a Script Include, the "Ask Jarvis" button and async
Business Rules on new incidents (suggestion + triage) and on resolved incidents (KB draft). Safe to re-run (updates records by name).

Usage: python -m seed.install_snow https://<public-url-of-jarvis-server>
"""
import os
import sys

from jarvis.config import snow_from_env

CLIENT = """var JarvisClient = Class.create();
JarvisClient.prototype = {
    initialize: function() {},

    // Fire-and-forget: Jarvis answers 202 and writes the work note itself
    ask: function(sysId, path) {
        var r = new sn_ws.RESTMessageV2();
        r.setEndpoint(gs.getProperty('jarvis.endpoint') + (path || '/suggest'));
        r.setHttpMethod('post');
        r.setRequestHeader('Content-Type', 'application/json');
        r.setRequestHeader('X-Jarvis-Token', gs.getProperty('jarvis.token'));
        r.setRequestBody(JSON.stringify({ sys_id: String(sysId) }));
        r.setHttpTimeout(10000);
        return r.executeAsync();
    },

    type: 'JarvisClient'
};"""

BUTTON = """new JarvisClient().ask(current.sys_id);
gs.addInfoMessage('Jarvis is analysing this incident: the suggestion will appear in the work notes in a few seconds.');
action.setRedirectURL(current);"""

RULE = """(function executeRule(current, previous) {
    new JarvisClient().ask(current.sys_id);
})(current, previous);"""

RESOLVED_RULE = """(function executeRule(current, previous) {
    new JarvisClient().ask(current.sys_id, '/kb-draft');
})(current, previous);"""


def upsert(snow, table, query, data):
    rec = snow.first(table, query)
    rec = snow.update(table, rec["sys_id"], data) if rec else snow.create(table, data)
    print(f"{table}: {data.get('name')} ok")
    return rec


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("https://"):
        raise SystemExit(__doc__)
    token = os.environ.get("JARVIS_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Set JARVIS_TOKEN (at least 16 random characters) in .env first.")
    snow = snow_from_env()
    upsert(snow, "sys_properties", "name=jarvis.endpoint",
           {"name": "jarvis.endpoint", "value": sys.argv[1].rstrip("/"), "type": "string",
            "description": "Public URL of the Jarvis server"})
    # shortcut: token stored as a plain admin-only property; use a password2 property + Connection & Credential alias in production
    upsert(snow, "sys_properties", "name=jarvis.token",
           {"name": "jarvis.token", "value": token, "type": "string", "description": "Shared secret sent to Jarvis"})
    upsert(snow, "sys_script_include", "name=JarvisClient",
           {"name": "JarvisClient", "script": CLIENT, "active": "true", "access": "package_private",
            "description": "Calls the Jarvis server to request a resolution suggestion"})
    upsert(snow, "sys_ui_action", "table=incident^name=Ask Jarvis",
           {"name": "Ask Jarvis", "table": "incident", "action_name": "ask_jarvis", "script": BUTTON,
            "condition": "current.active == true", "form_button": "true", "workspace_form_button": "true",
            "client": "false", "active": "true", "order": "100", "hint": "Ask Jarvis for a resolution suggestion"})
    upsert(snow, "sys_script", "collection=incident^name=Jarvis: suggest on new incident",
           {"name": "Jarvis: suggest on new incident", "collection": "incident", "when": "async",
            "action_insert": "true", "advanced": "true", "active": "true", "order": "100", "script": RULE})
    upsert(snow, "sys_script", "collection=incident^name=Jarvis: draft KB on resolve",
           {"name": "Jarvis: draft KB on resolve", "collection": "incident", "when": "async",
            "action_update": "true", "filter_condition": "stateCHANGESTO6^EQ", "advanced": "true", "active": "true",
            "order": "100", "script": RESOLVED_RULE})


if __name__ == "__main__":
    main()

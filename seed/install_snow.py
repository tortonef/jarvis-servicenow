"""Install the ServiceNow side of push mode: system properties, a Script Include, the "Ask Jarvis" button and async
Business Rules on new incidents (suggestion + triage) and on resolved incidents (KB draft), plus the
"Approve Jarvis procedure" button for L1 procedures, the "Helios Group IT" knowledge base and the Jarvis KB API that publishes
the docs repository into it. Safe to re-run (updates records by name).

Usage: python -m seed.install_snow https://<public-url-of-jarvis-server>
"""
import os
import sys
from pathlib import Path

from jarvis.config import KB_TITLE, snow_from_env
from jarvis.snow import APPROVAL, FEEDBACK, OUTCOME, PROPOSAL, SUGGESTION

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

    // Synchronous call for the self-service portal widget: returns { status, body }
    askSync: function(path, payload) {
        var r = new sn_ws.RESTMessageV2();
        r.setEndpoint(gs.getProperty('jarvis.endpoint') + path);
        r.setHttpMethod('post');
        r.setRequestHeader('Content-Type', 'application/json');
        r.setRequestHeader('X-Jarvis-Token', gs.getProperty('jarvis.token'));
        r.setRequestBody(JSON.stringify(payload));
        r.setHttpTimeout(30000);
        try {
            var res = r.execute();
            return { status: res.getStatusCode(), body: JSON.parse(res.getBody() || '{}') };
        } catch (e) {
            return { status: 0, body: {} };
        }
    },

    // True when Jarvis has posted a resolution suggestion on the incident (the rating buttons need one)
    hasSuggestion: function(sysId) {
        var j = new GlideRecord('sys_journal_field');
        j.addQuery('element_id', String(sysId));
        j.addQuery('element', 'work_notes');
        j.addQuery('value', 'STARTSWITH', '""" + SUGGESTION + """');
        j.setLimit(1);
        j.query();
        return j.hasNext();
    },

    // True while the latest Jarvis procedure note on the incident is a proposal nobody approved yet
    pendingProposal: function(sysId) {
        var j = new GlideRecord('sys_journal_field');
        j.addQuery('element_id', String(sysId));
        j.addQuery('element', 'work_notes');
        var q = j.addQuery('value', 'STARTSWITH', '""" + PROPOSAL + """');
        q.addOrCondition('value', 'STARTSWITH', '""" + APPROVAL + """');
        q.addOrCondition('value', 'STARTSWITH', '""" + OUTCOME + """');
        j.orderByDesc('sys_created_on');
        j.setLimit(1);
        j.query();
        return j.next() && String(j.value).indexOf('""" + PROPOSAL + """') === 0;
    },

    type: 'JarvisClient'
};"""

BUTTON = """new JarvisClient().ask(current.sys_id);
gs.addInfoMessage('Jarvis is analysing this incident: the suggestion will appear in the work notes in a few seconds.');
action.setRedirectURL(current);"""

RULE = """(function executeRule(current, previous) {
    new JarvisClient().ask(current.sys_id);
})(current, previous);"""

# The agent's click is the approval: recorded as a work note in their name (Jarvis reads the author), then Jarvis acts
APPROVE_BUTTON = """current.work_notes = '""" + APPROVAL + """ (' + gs.getUserDisplayName() + ').';
current.update();
new JarvisClient().ask(current.sys_id, '/approve');
gs.addInfoMessage('Approved: Jarvis is running the procedure on-prem and will report the result in the work notes.');
action.setRedirectURL(current);"""

# Server-side because the Table API cannot edit or publish articles once they are published (it answers 403)
KB_API = """(function process(request, response) {
    var b = request.body.data;
    if (!b || !b.doc_id || !b.kb || (!b.retire && (!b.title || !b.html))) {
        response.setStatus(400);
        return { error: 'doc_id and kb are required, plus title and html unless retire is true' };
    }
    var kb = new GlideRecord('kb_knowledge_base');
    if (!kb.get('title', b.kb)) {
        response.setStatus(404);
        return { error: 'knowledge base not found: ' + b.kb };
    }
    var tag = 'jarvis-doc:' + b.doc_id;
    var gr = new GlideRecord('kb_knowledge');
    gr.addQuery('kb_knowledge_base', kb.getUniqueValue());
    gr.addQuery('meta', 'CONTAINS', tag);
    gr.addQuery('workflow_state', '!=', 'retired');
    gr.orderByDesc('sys_created_on');
    gr.query();
    var found = gr.next();
    if (b.retire) {
        if (found) { gr.workflow_state = 'retired'; gr.update(); }
        return { retired: found, number: found ? String(gr.number) : null };
    }
    if (!found) {
        gr.initialize();
        gr.kb_knowledge_base = kb.getUniqueValue();
    }
    gr.short_description = b.title;
    gr.text = b.html;
    gr.meta = tag + (b.keywords ? ' ' + b.keywords : '');
    if (!found) {
        // the KB rules force a new article to draft while it is inserted: publish it with a separate write on a fresh
        // copy of the record, as a reviewer would (the review already happened in the pull request)
        var id = gr.insert();
        gr = new GlideRecord('kb_knowledge');
        gr.get(id);
    }
    gr.workflow_state = 'published';
    gr.update();
    return { number: String(gr.number), sys_id: gr.getUniqueValue(), created: !found };
})(request, response);"""

DIAGNOSE_BUTTON = """new JarvisClient().ask(current.sys_id, '/diagnose');
gs.addInfoMessage('Jarvis is checking the Active Directory account of the caller through the MID Server.');
action.setRedirectURL(current);"""

IMPLEMENT_RULE = """(function executeRule(current, previous) {
    new JarvisClient().ask(current.sys_id, '/implement');
})(current, previous);"""

def rating_button(helpful):
    """The vote is a work note in the agent's name: Jarvis reads author and verdict back from ServiceNow."""
    verdict = "helpful" if helpful else "not helpful"
    return (f"current.work_notes = '{FEEDBACK} {verdict} (' + gs.getUserDisplayName() + ').';\n"
            "current.update();\n"
            "new JarvisClient().ask(current.sys_id, '/feedback');\n"
            "gs.addInfoMessage('Thanks: your rating of the Jarvis suggestion is recorded.');\n"
            "action.setRedirectURL(current);")


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
    install(snow_from_env("keyword"), sys.argv[1], token)  # no search here: skip loading the embedding model


def install(snow, endpoint, token):
    # Own KB with "Instant Publish": the stock "IT" KB has an approval flow; here the approval is the pull request
    if not snow.first("kb_knowledge_base", f"title={KB_TITLE}"):
        flow = snow.first("sys_hub_flow", "name=Knowledge - Instant Publish")
        snow.create("kb_knowledge_base", {"title": KB_TITLE, "kb_publish_flow": flow["sys_id"] if flow else ""})
        print(f"kb_knowledge_base: {KB_TITLE} created")
    # Run on the MID Server, called by Jarvis through the ECC queue (jarvis/mid.py)
    for js in sorted((Path(__file__).parent / "mid").glob("*.js")):
        upsert(snow, "ecc_agent_script_include", f"name={js.stem}",
               {"name": js.stem, "active": "true", "script": js.read_text(encoding="utf-8"),
                "description": "Jarvis MID function (lab: helios.local)"})
    api = upsert(snow, "sys_ws_definition", "service_id=jarvis_kb",
                 {"name": "Jarvis KB", "service_id": "jarvis_kb", "active": "true",
                  "short_description": "Publishes the Helios docs repository into the knowledge base"})
    upsert(snow, "sys_ws_operation", f"web_service_definition={api['sys_id']}^relative_path=/articles",
           {"name": "articles", "web_service_definition": api["sys_id"], "http_method": "POST", "relative_path": "/articles",
            "active": "true", "requires_authentication": "true", "operation_script": KB_API})
    upsert(snow, "sys_properties", "name=jarvis.endpoint",
           {"name": "jarvis.endpoint", "value": endpoint.rstrip("/"), "type": "string",
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
    # Replaced by the generic approval below: kept inactive, not deleted, so the change is reversible
    if snow.first("sys_ui_action", "table=incident^name=Unlock account (Jarvis)"):
        upsert(snow, "sys_ui_action", "table=incident^name=Unlock account (Jarvis)",
               {"name": "Unlock account (Jarvis)", "active": "false"})
    upsert(snow, "sys_ui_action", "table=incident^name=Approve Jarvis procedure",
           {"name": "Approve Jarvis procedure", "table": "incident", "action_name": "jarvis_approve", "script": APPROVE_BUTTON,
            "condition": "current.active && new JarvisClient().pendingProposal(current.sys_id)",
            "form_button": "true", "workspace_form_button": "true", "client": "false", "active": "true", "order": "110",
            "hint": "Approve the L1 procedure Jarvis proposed in the work notes"})
    upsert(snow, "sys_ui_action", "table=incident^name=Check AD account (Jarvis)",
           {"name": "Check AD account (Jarvis)", "table": "incident", "action_name": "jarvis_ad_check", "script": DIAGNOSE_BUTTON,
            "condition": "current.active && !current.caller_id.nil()", "form_button": "true", "workspace_form_button": "true",
            "client": "false", "active": "true", "order": "105",
            "hint": "Read-only: check the caller's lockout state in Active Directory"})
    for helpful in (True, False):
        name = f"Jarvis: {'helpful' if helpful else 'not helpful'}"
        upsert(snow, "sys_ui_action", f"table=incident^name={name}",
               {"name": name, "table": "incident", "action_name": f"jarvis_rate_{'up' if helpful else 'down'}",
                "script": rating_button(helpful), "condition": "new JarvisClient().hasSuggestion(current.sys_id)",
                "form_button": "true", "workspace_form_button": "true", "client": "false", "active": "true",
                "order": "120" if helpful else "121", "hint": "Rate Jarvis's resolution suggestion on this ticket"})
    install_portal(snow)
    # L2 procedures: Jarvis acts when the approved Change it filed moves to Implement
    upsert(snow, "sys_script", "collection=change_request^name=Jarvis: implement approved change",
           {"name": "Jarvis: implement approved change", "collection": "change_request", "when": "async",
            "action_update": "true", "filter_condition": "correlation_idSTARTSWITHjarvis-exec-^stateCHANGESTO-1^EQ",
            "advanced": "true", "active": "true", "order": "100", "script": IMPLEMENT_RULE})
    upsert(snow, "sys_script", "collection=incident^name=Jarvis: draft KB on resolve",
           {"name": "Jarvis: draft KB on resolve", "collection": "incident", "when": "async",
            "action_update": "true", "filter_condition": "stateCHANGESTO6^EQ", "advanced": "true", "active": "true",
            "order": "100", "script": RESOLVED_RULE})


if __name__ == "__main__":
    main()


def install_portal(snow):
    """Self-service page on the Service Portal: /sp?id=jarvis_help with the 'Ask Jarvis' widget."""
    files = Path(__file__).parent / "portal"
    widget = upsert(snow, "sp_widget", "id=jarvis_ask", {
        "name": "Ask Jarvis", "id": "jarvis_ask",
        "template": (files / "template.html").read_text(encoding="utf-8"),
        "client_script": (files / "client.js").read_text(encoding="utf-8"),
        "script": (files / "server.js").read_text(encoding="utf-8"),
        "css": (files / "style.css").read_text(encoding="utf-8")})
    page = upsert(snow, "sp_page", "id=jarvis_help", {"id": "jarvis_help", "title": "IT help - Ask Jarvis"})
    container = snow.first("sp_container", f"sp_page={page['sys_id']}") or \
        snow.create("sp_container", {"sp_page": page["sys_id"], "order": "1", "width": "container"})
    row = snow.first("sp_row", f"sp_container={container['sys_id']}") or \
        snow.create("sp_row", {"sp_container": container["sys_id"], "order": "1"})
    column = snow.first("sp_column", f"sp_row={row['sys_id']}") or \
        snow.create("sp_column", {"sp_row": row["sys_id"], "order": "1", "size": "12"})
    if not snow.first("sp_instance", f"sp_column={column['sys_id']}^sp_widget={widget['sys_id']}"):
        snow.create("sp_instance", {"sp_column": column["sys_id"], "sp_widget": widget["sys_id"], "order": "1"})
    print("portal: /sp?id=jarvis_help ok")

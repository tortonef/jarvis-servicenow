// Run in ServiceNow: System Definition > Scripts - Background.
// Publishes the Jarvis demo articles (the Table API cannot change workflow_state).
var gr = new GlideRecord('kb_knowledge');
gr.addQuery('kb_knowledge_base.title', 'IT Service Desk (Jarvis demo)');
gr.addQuery('workflow_state', '!=', 'published');
gr.query();
var n = 0;
while (gr.next()) {
    gr.workflow_state = 'published';
    gr.update();
    n++;
}
gs.print('Published ' + n + ' Jarvis demo articles');

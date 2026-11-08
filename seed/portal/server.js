(function() {
    // Runs as the signed-in employee. Jarvis gets only the question and the user name; the ticket is created here.
    if (!input || !input.action) return;
    var client = new JarvisClient();

    if (input.action == 'ask') {
        var question = String(input.question || '').substring(0, 1000);
        if (question.replace(/\s/g, '').length < 3) {
            data.error = 'Please describe the problem.';
            return;
        }
        var r = client.askSync('/ask', { question: question, user: gs.getUserName() });
        if (r.status != 200) {
            data.error = 'Jarvis is not available right now: please open a ticket.';
            return;
        }
        data.id = r.body.id;
        data.answer = r.body.answer;
        data.articles = r.body.articles;
    }

    if (input.action == 'outcome') {
        var outcome = { id: parseInt(input.id, 10), solved: input.solved === true };
        if (!outcome.solved) {
            var inc = new GlideRecord('incident');
            inc.initialize();
            inc.caller_id = gs.getUserID();
            inc.contact_type = 'self-service';
            inc.short_description = String(input.question || '').substring(0, 160);
            inc.description = String(input.question || '') +
                '\n\nAlready tried with Jarvis self-service, did not solve it:\n' + String(input.answer || '');
            inc.insert();
            outcome.incident = String(inc.number);
            data.incident = outcome.incident;
        }
        client.askSync('/ask-outcome', outcome);
    }
})();

api.controller = function() {
    var c = this;
    c.result = {};

    c.ask = function() {
        c.busy = true;
        c.result = {};
        c.done = null;
        c.incident = null;
        c.server.get({ action: 'ask', question: c.question }).then(function(r) {
            c.busy = false;
            c.result = r.data;
        });
    };

    c.outcome = function(solved) {
        c.server.get({ action: 'outcome', id: c.result.id, solved: solved, question: c.question, answer: c.result.answer })
            .then(function(r) {
                c.done = solved ? 'solved' : 'ticket';
                c.incident = r.data.incident;
            });
    };
};

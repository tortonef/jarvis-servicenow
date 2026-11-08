// MID Server Script Include, installed by seed/install_snow.py. Runs one named verb on one allowed lab server over SSH.
// The target binds the key to /usr/local/bin/jarvis-agent, which knows the same verbs: two independent allowlists.
var JarvisSsh = Class.create();
JarvisSsh.prototype = {
    VERBS: ['disk_usage', 'clean_logs', 'portal_health', 'restart_portal'],

    initialize: function() {
        this.hosts = String(Packages.java.lang.System.getenv().get('JARVIS_SSH_HOSTS') || '').split(',');
    },

    // Returns the JSON line the target printed, or a JSON error
    run: function(host, verb) {
        host = String(host || '');
        verb = String(verb || '');
        if (this.hosts.indexOf(host) < 0) return JSON.stringify({ error: 'host not allowed: ' + host });
        if (this.VERBS.indexOf(verb) < 0) return JSON.stringify({ error: 'verb not allowed: ' + verb });
        var r = new JarvisExec().run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=accept-new',
                                      '-o', 'ConnectTimeout=10', 'jarvis@' + host, verb], null, null, 30);
        var last = r.output.length ? r.output[r.output.length - 1] : '';
        try {
            var data = JSON.parse(last);
            data.host = host;
            return JSON.stringify(data);
        } catch (e) {
            return JSON.stringify({ host: host, error: 'ssh failed (' + r.code + '): ' + r.output.join(' ').substring(0, 300) });
        }
    },

    type: 'JarvisSsh'
};

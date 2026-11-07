// MID Server Script Include, installed by seed/install_snow.py. Runs ON the MID Server (Rhino, ES5), called by Jarvis
// through a JavascriptProbe. Only fixed, named functions are exposed; arguments are validated before they reach LDAP.
var JarvisLdap = Class.create();
JarvisLdap.prototype = {
    initialize: function() {
        // Set on the MID container (docker-compose.yml): the bind password never goes through ServiceNow
        var env = Packages.java.lang.System.getenv();
        this.url = String(env.get('JARVIS_LDAP_URL') || '');
        this.base = String(env.get('JARVIS_LDAP_BASE') || '');
        this.bindDn = String(env.get('JARVIS_LDAP_BIND_DN') || '');
        this.password = String(env.get('JARVIS_LDAP_PASSWORD') || '');
    },

    // L0, read only: is this account locked out, since when, and when does it unlock by itself? Returns JSON text.
    lockoutStatus: function(account) {
        account = String(account || '');
        if (!/^[A-Za-z0-9._-]{1,64}$/.test(account))  // nothing else may reach the LDAP filter
            return JSON.stringify({ error: 'invalid account name' });
        var user = this._search(this.base, 'sub', '(&(objectClass=user)(sAMAccountName=' + account + '))',
                                ['distinguishedName', 'lockoutTime', 'badPwdCount', 'userAccountControl']);
        if (user.error) return JSON.stringify(user);
        if (!user.distinguishedName) return JSON.stringify({ account: account, found: false });
        var domain = this._search(this.base, 'base', '(objectClass=*)', ['lockoutDuration', 'lockoutThreshold']);
        if (domain.error) return JSON.stringify(domain);
        var lockoutTime = Number(user.lockoutTime || 0);
        var durationMs = Math.abs(Number(domain.lockoutDuration || 0)) / 10000;    // AD stores 100-ns intervals
        var since = lockoutTime > 0 ? lockoutTime / 10000 - 11644473600000 : null; // Windows FILETIME -> epoch ms
        var locked = since !== null && (durationMs === 0 || new Date().getTime() < since + durationMs);
        return JSON.stringify({
            account: account,
            found: true,
            dn: user.distinguishedName,
            locked: locked,
            locked_since: since !== null ? new Date(since).toISOString() : null,
            unlocks_at: locked && durationMs ? new Date(since + durationMs).toISOString() : null,
            bad_password_count: Number(user.badPwdCount || 0),
            lockout_threshold: Number(domain.lockoutThreshold || 0),
            disabled: (Number(user.userAccountControl || 0) & 2) === 2
        });
    },

    _search: function(base, scope, filter, attrs) {
        var args = ['ldapsearch', '-LLL', '-o', 'ldif-wrap=no', '-x', '-H', this.url, '-D', this.bindDn,
                    // shortcut: -w puts the password in the MID container's process list; use -y with a mounted secret file in production
                    '-w', this.password, '-b', base, '-s', scope, filter].concat(attrs);
        var cmd = new Packages.java.util.ArrayList();
        for (var i = 0; i < args.length; i++) cmd.add(args[i]);  // no shell: arguments are never interpreted
        var pb = new Packages.java.lang.ProcessBuilder(cmd);
        pb.environment().put('LDAPTLS_REQCERT', 'never');  // shortcut: the lab DC has a self-signed certificate
        pb.redirectErrorStream(true);
        var proc = pb.start();
        var reader = new Packages.java.io.BufferedReader(new Packages.java.io.InputStreamReader(proc.getInputStream()));
        var result = {}, lines = [], line;
        while ((line = reader.readLine()) !== null) {
            line = String(line);
            lines.push(line);
            var sep = line.indexOf(': ');
            if (sep > 0 && line.charAt(0) !== '#') result[line.substring(0, sep)] = line.substring(sep + 2);
        }
        if (!proc.waitFor(15, Packages.java.util.concurrent.TimeUnit.SECONDS)) {
            proc.destroy();
            return { error: 'ldapsearch timed out' };
        }
        if (proc.exitValue() !== 0) return { error: 'ldapsearch failed: ' + lines.join(' ').substring(0, 300) };
        return result;
    },

    type: 'JarvisLdap'
};

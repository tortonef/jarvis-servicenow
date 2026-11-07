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
        this.staff = ',OU=Staff,' + this.base;  // the only place unlock may act (AD enforces it too, by delegation)
    },

    // L0, read only: is this account locked out, since when, and when does it unlock by itself? Returns JSON text.
    lockoutStatus: function(account) {
        var user = this._user(account);
        if (user.error || !user.found) return JSON.stringify(user);
        var domain = this._search(this.base, 'base', '(objectClass=*)', ['lockoutDuration', 'lockoutThreshold']);
        if (domain.error) return JSON.stringify(domain);
        var lockoutTime = Number(user.lockoutTime || 0);
        var durationMs = Math.abs(Number(domain.lockoutDuration || 0)) / 10000;    // AD stores 100-ns intervals
        var since = lockoutTime > 0 ? lockoutTime / 10000 - 11644473600000 : null; // Windows FILETIME -> epoch ms
        var locked = since !== null && (durationMs === 0 || new Date().getTime() < since + durationMs);
        return JSON.stringify({
            account: user.account,
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

    // L1, needs an approved Jarvis procedure: clear the lockout of one account under OU=Staff. Returns JSON text.
    unlock: function(account) {
        var user = this._user(account);
        if (user.error || !user.found) return JSON.stringify(user);
        var dn = String(user.distinguishedName);
        var at = dn.toLowerCase().lastIndexOf(this.staff.toLowerCase());
        if (at < 0 || at !== dn.length - this.staff.length)  // must END with ,OU=Staff,<base>
            return JSON.stringify({ account: user.account, error: 'account is outside OU=Staff: not allowed' });
        var ldif = 'dn: ' + dn + '\nchangetype: modify\nreplace: lockoutTime\nlockoutTime: 0\n';
        var r = new JarvisExec().run(['ldapmodify', '-x', '-H', this.url, '-D', this.bindDn, '-w', this.password],
                                     ldif, { LDAPTLS_REQCERT: 'never' }, 15);
        if (r.code !== 0) return JSON.stringify({ account: user.account, error: 'ldapmodify failed: ' + r.output.join(' ').substring(0, 300) });
        return JSON.stringify({ account: user.account, unlocked: true, dn: dn });
    },

    _user: function(account) {
        account = String(account || '');
        if (!/^[A-Za-z0-9._-]{1,64}$/.test(account))  // nothing else may reach the LDAP filter
            return { error: 'invalid account name' };
        var user = this._search(this.base, 'sub', '(&(objectClass=user)(sAMAccountName=' + account + '))',
                                ['distinguishedName', 'lockoutTime', 'badPwdCount', 'userAccountControl']);
        if (user.error) return user;
        user.account = account;
        user.found = !!user.distinguishedName;
        return user;
    },

    _search: function(base, scope, filter, attrs) {
        // shortcut: -w puts the password in the MID container's process list; use -y with a mounted secret file in production
        var args = ['ldapsearch', '-LLL', '-o', 'ldif-wrap=no', '-x', '-H', this.url, '-D', this.bindDn, '-w', this.password,
                    '-b', base, '-s', scope, filter].concat(attrs);
        // shortcut: the lab DC has a self-signed certificate
        var r = new JarvisExec().run(args, null, { LDAPTLS_REQCERT: 'never' }, 15);
        if (r.code !== 0) return { error: 'ldapsearch failed: ' + r.output.join(' ').substring(0, 300) };
        var result = {};
        for (var i = 0; i < r.output.length; i++) {
            var sep = r.output[i].indexOf(': ');
            if (sep > 0 && r.output[i].charAt(0) !== '#') result[r.output[i].substring(0, sep)] = r.output[i].substring(sep + 2);
        }
        return result;
    },

    type: 'JarvisLdap'
};

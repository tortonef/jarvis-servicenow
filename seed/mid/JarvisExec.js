// MID Server Script Include, installed by seed/install_snow.py. Shared by JarvisLdap and JarvisSsh: runs one local
// process with an argument list (no shell, so arguments are never interpreted), optional stdin and a timeout.
var JarvisExec = Class.create();
JarvisExec.prototype = {
    initialize: function() {},

    // Returns { code: exit code (or -1 on timeout), output: stdout + stderr lines }
    run: function(args, input, env, timeoutSeconds) {
        var cmd = new Packages.java.util.ArrayList();
        for (var i = 0; i < args.length; i++) cmd.add(String(args[i]));
        var pb = new Packages.java.lang.ProcessBuilder(cmd);
        for (var k in (env || {})) pb.environment().put(k, String(env[k]));
        pb.redirectErrorStream(true);
        var proc = pb.start();
        if (input) {
            var w = new Packages.java.io.OutputStreamWriter(proc.getOutputStream(), 'UTF-8');
            w.write(String(input));
            w.close();
        } else {
            proc.getOutputStream().close();
        }
        var reader = new Packages.java.io.BufferedReader(new Packages.java.io.InputStreamReader(proc.getInputStream()));
        var lines = [], line;
        while ((line = reader.readLine()) !== null) lines.push(String(line));
        if (!proc.waitFor(timeoutSeconds || 20, Packages.java.util.concurrent.TimeUnit.SECONDS)) {
            proc.destroy();
            return { code: -1, output: lines.concat(['timed out']) };
        }
        return { code: proc.exitValue(), output: lines };
    },

    type: 'JarvisExec'
};

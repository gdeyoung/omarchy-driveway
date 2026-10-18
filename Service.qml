import QtQuick
import Quickshell.Io
import "Model.js" as Model

// gdeyoung.driveway service — owns every backend call. The Panel renders;
// this decides (rclone-bs's "render-only panel" rule).
//
// Data:  `driveway list` (udev-triggered + polled), `driveway cloud status`.
// Acts:  `driveway action …` (udisks mount/eject/busy machinery, vendored
//        from jgarza9788/drives — see NOTICE.md) and
//        `driveway cloud mount/unmount` (systemd user units).
//
// A list run past 20s is abandoned, never waited on (jgarza pattern), so a
// wedged FUSE/NFS mount cannot freeze the shell widget.
Item {
  id: root

  property var settings: ({})
  property bool panelOpen: false

  property var drives: []          // lister rows (incl. the System row)
  property var cloud: ({ rclone: false, unit: false, mountRoot: "", drives: [] })
  property var cloudDiag: ({})        // name -> {state, problem, remedy}
  property var cloudProviders: []     // from `cloud providers` once at start
  property var busy: ({})          // drive.key -> {message, procs, uploads}
  property string lastError: ""

  // ---- network mapping (v0.2) ------------------------------------------------
  property var netServers: []      // avahi discovery rows
  property var netShares: []       // shares of the browsed server
  property string netSharesServer: ""
  property var netMaps: []         // saved maps
  property var netMounted: []      // currently mounted gvfs network locations
  property bool netDiscovering: false
  property bool netListingShares: false
  property bool netMounting: false
  property string netError: ""
  // cloud add wizard: state idle -> picking -> working -> done/error
  property var cloudWizard: ({ state: "idle", provider: "", label: "" })

  // emitted when a browsed server refuses guest listing: the wizard should
  // surface credential fields for that server
  signal netNeedsCreds(string server)

  readonly property int pollMs: Math.max(2, Number(setting("pollIntervalSec", 10)) || 10) * 1000
  readonly property bool showNetwork: setting("showNetwork", true) !== false
  readonly property bool showUnmounted: setting("showUnmounted", true) !== false
  readonly property real minUnmountedMb: Number(setting("minUnmountedMb", 64))
  readonly property real thumbMaxGb: Number(setting("thumbMaxGb", 256)) || 256
  readonly property int fullWarnPct: Number(setting("fullWarnPct", 90)) || 90

  readonly property var networkDrives: {
    var out = []
    var list = root.drives
    for (var i = 0; i < list.length; i++)
      if (list[i].kind === "network") out.push(list[i])
    return out
  }
  readonly property var cloudDrives: root.cloud.drives || []
  readonly property var barState: Model.barState(root.drives, root.cloudDrives,
                                                  root.cloud.rclone, root.fullWarnPct)

  function setting(name, fallback) {
    var value = settings ? settings[name] : undefined
    return value === undefined || value === null ? fallback : value
  }

  function script(name) {
    var value = String(Qt.resolvedUrl("bin/" + name))
    return value.indexOf("file://") === 0 ? decodeURIComponent(value.substring(7)) : value
  }

  function q(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'" }

  // ---- data ----------------------------------------------------------------

  property var lister: null
  property real listerStarted: 0
  readonly property int listerTimeoutMs: 20000
  property bool refreshAgain: false

  function refresh() {
    refreshList()
    refreshCloud()
    refreshNetwork()
    loadProviders()
  }

  function refreshList() {
    if (lister) {
      if (Date.now() - listerStarted < listerTimeoutMs) { refreshAgain = true; return }
      console.warn("gdeyoung.driveway: list still running after 20s; abandoning it")
      lister.abandoned = true
      lister.running = false
      lister = null
    }
    var cmd = [script("driveway"), "list", "--thumb-max-gb", String(thumbMaxGb)]
    if (!showNetwork) cmd.push("--no-network")
    if (!showUnmounted) cmd.push("--no-unmounted")
    cmd.push("--min-unmounted-mb", String(minUnmountedMb))
    lister = listerProcess.createObject(root, { command: cmd })
    listerStarted = Date.now()
    lister.running = true
  }

  function refreshCloud() {
    cloudProc.command = [script("driveway"), "cloud", "status"]
    cloudProc.running = true
  }

  Component {
    id: listerProcess
    Process {
      id: listerRun
      property bool abandoned: false
      stdout: StdioCollector {
        onStreamFinished: {
          if (listerRun.abandoned) return
          try {
            var data = JSON.parse(text)
            root.drives = data.drives || []
            if (data.error) root.lastError = data.error
          } catch (e) {
            console.warn("gdeyoung.driveway: bad list output", e)
          }
        }
      }
      onExited: {
        if (root.lister === listerRun) {
          root.lister = null
          if (root.refreshAgain) { root.refreshAgain = false; root.refreshList() }
        }
        destroy()
      }
    }
  }

  Process {
    id: cloudProc
    stdout: StdioCollector {
      onStreamFinished: {
        try {
          root.cloud = JSON.parse(text)
          root._chaseDiagnoses()
        } catch (e) {
          console.warn("gdeyoung.driveway: bad cloud output", e)
        }
      }
    }
  }

  // Kernel block events (plug, unplug, media change); mount lands a beat
  // after the add event, so debounce and re-check.
  Process {
    id: monitor
    command: ["udevadm", "monitor", "--kernel", "--subsystem-match=block"]
    running: true
    stdout: SplitParser {
      onRead: function(line) { debounce.restart(); settle.restart() }
    }
    onRunningChanged: if (!running) retryMonitor.restart()
  }
  Timer { id: debounce; interval: 500; onTriggered: root.refreshList() }
  Timer { id: settle; interval: 2500; onTriggered: root.refreshList() }
  // The monitor dying (uaccess races at login) must not silently end live
  // updates — restart it with backoff (arsinghin pattern).
  Timer {
    id: retryMonitor
    interval: 5000
    onTriggered: { monitor.running = true }
  }

  Timer {
    interval: root.panelOpen ? 2000 : root.pollMs
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  // ---- actions -------------------------------------------------------------

  function displayName(d) { return d.label || d.name || Model.kindName(d) }

  function open(d) {
    if (d.kind === "system") return run(["xdg-open", "/"])
    if (d.locked) return unlock(d)
    if (!d.mounted) return mount(d, true, false)
    run(["xdg-open", d.mountpoint])
  }

  function openTerminal(d) {
    if (d.kind === "system") return run(["foot", "--working-directory", "/"])
    if (d.locked) return
    if (!d.mounted) return mount(d, false, true)
    run(["foot", "--working-directory", d.mountpoint])
  }

  function mount(d, thenOpen, thenTerminal) {
    run([script("driveway"), "action", "mount", "--dev", d.path, "--name", displayName(d)],
         function(result) {
      if (result.status === "ok" && result.mountpoint) {
        if (thenOpen) run(["xdg-open", result.mountpoint])
        if (thenTerminal) run(["foot", "--working-directory", result.mountpoint])
      }
    })
  }

  // Passphrase goes into a terminal (udisksctl prompts on its tty), never
  // through the shell.
  function unlock(d) {
    run(["omarchy-launch-floating-terminal-with-presentation",
         q(script("driveway")) + " action unlock --dev " + q(d.path) + " --name " + q(displayName(d))])
  }

  function eject(d, kill, force) {
    if (!d.mounted || !d.eject) return
    if (d.pending > 0 && !force) {
      setBusy(d, { status: "busy", procs: [], uploads: d.pending,
                   message: d.pending + " upload" + (d.pending === 1 ? "" : "s") +
                     " still pending — unmounting now leaves them in rclone's cache until it is mounted again" })
      return
    }
    var cmd = [script("driveway"), "action", "eject", "--mode", d.eject,
               "--mount", d.mountpoint, "--name", displayName(d)]
    if (d.path && d.eject !== "fuse" && d.eject !== "gio") cmd.push("--dev", d.path)
    if (d.disk) cmd.push("--disk", d.disk)
    if (d.encrypted && d.luksPath) cmd.push("--luks", d.luksPath)
    if (d.removable) cmd.push("--removable")
    if (kill) cmd.push("--kill")
    run(cmd, function(result) { setBusy(d, result) })
  }

  function setBusy(d, result) {
    var next = Object.assign({}, root.busy)
    if (result && result.status === "busy")
      next[d.key] = { message: result.message, procs: result.procs || [], uploads: result.uploads || 0 }
    else delete next[d.key]
    root.busy = next
  }

  function busyFor(d) { return root.busy[d.key] || null }

  function clearBusy(d) {
    var next = Object.assign({}, root.busy)
    delete next[d.key]
    root.busy = next
  }

  function cloudMount(name) {
    run([script("driveway"), "cloud", "mount", name], function(result) {
      if (!result.ok) root.lastError = result.message || "mount failed"
      root.refreshCloud()
    })
  }

  // One-click rclone install: floating terminal with the sudo command
  // pre-loaded (same pattern as LUKS unlock — password typing stays in a
  // real terminal, never in the shell). Panel polls rclone state after.
  function installRclone() {
    run(["omarchy-launch-floating-terminal-with-presentation",
         "sudo pacman -S --needed rclone gvfs-nfs"])
  }

  // ---- v0.3: quotas, mount-all, diagnose/remedy, providers ------------------

  function loadProviders() {
    if (cloudProviders.length) return
    run([script("driveway"), "cloud", "providers"], function(result) {
      if (result && result.providers) root.cloudProviders = result.providers
    })
  }

  // After each cloud status: if any remote looks unhealthy, ask the
  // backend WHY (one at a time — each diagnose runs bounded commands).
  function _chaseDiagnoses() {
    var bad = []
    var ds = root.cloud.drives || []
    for (var i = 0; i < ds.length; i++) {
      var s = ds[i].state
      if (s === "failed" || s === "hung" || s === "starting")
        bad.push(ds[i].name)
    }
    var next = {}
    for (var j = 0; j < bad.length; j++) next[bad[j]] = root.cloudDiag[bad[j]] || null
    root.cloudDiag = next
    if (bad.length) _diagnoseNext(bad)
  }

  function _diagnoseNext(queue) {
    if (!queue || !queue.length) return
    var name = queue[0]
    var rest = queue.slice(1)
    run([script("driveway"), "cloud", "diagnose", name], function(result) {
      var d = {}
      for (var k in root.cloudDiag) d[k] = root.cloudDiag[k]
      d[name] = result
      root.cloudDiag = d
      _diagnoseNext(rest)
    })
  }

  function cloudMountAll() {
    run([script("driveway"), "cloud", "mount-all"], function(result) {
      if (!result.ok) root.lastError = result.message || "mount-all failed"
      refreshCloud()
    })
  }

  function cloudUnmountAll() {
    run([script("driveway"), "cloud", "unmount-all"], function(result) {
      if (!result.ok) root.lastError = result.message || "unmount-all failed"
      refreshCloud()
    })
  }

  function cloudRestart(name) {
    run([script("driveway"), "cloud", "restart", name], function() {
      refreshCloud()
    })
  }

  // Expired sign-in: stops the unit, opens the browser, waits for you
  // (up to 5.5 min), then remounts.
  function cloudReconnect(name) {
    var d = {}
    for (var k in root.cloudDiag) d[k] = root.cloudDiag[k]
    d[name] = { state: "reconnecting", problem: "waiting for browser sign-in…",
                remedy: null }
    root.cloudDiag = d
    runWithStdin([script("driveway"), "cloud", "reconnect", name], "{}",
                 function(result) {
      if (result.ok) {
        cloudMount(name)
      } else {
        root.lastError = result.message || "reconnect failed"
        refreshCloud()
      }
    }, true, 330000)
  }

  // Any rclone backend we don't template: rclone's own questionnaire.
  function cloudOtherConfig() {
    run(["omarchy-launch-floating-terminal-with-presentation", "rclone config"])
  }

  // ---- network mapping -------------------------------------------------------

  function refreshNetwork() {
    run([script("driveway"), "netmap", "list"], function(result) {
      root.netMaps = result.maps || []
      root.netMounted = result.mounted || []
    }, true)
  }

  function netDiscover() {
    netDiscovering = true
    netError = ""
    run([script("driveway"), "netmap", "discover"], function(result) {
      netDiscovering = false
      netServers = result.servers || []
    }, true)
  }

  function netBrowseShares(server, user, domain, password) {
    netListingShares = true
    netSharesServer = server
    netError = ""
    runWithStdin([script("driveway"), "netmap", "shares", server],
                 JSON.stringify({ user: user || null, domain: domain || null,
                                  password: password || null }),
                 function(result) {
      netListingShares = false
      if (result.needs_creds) {
        netError = "server requires a login"
        netShares = []
        root.netNeedsCreds(server)
      } else {
        netShares = result.shares || []
      }
    }, true)
  }

  // spec carries credentials; it goes over stdin, never argv (house rule)
  function netMap(spec, onDone) {
    netMounting = true
    netError = ""
    runWithStdin([script("driveway"), "netmap", "mount"],
                 JSON.stringify(spec),
                 function(result) {
      netMounting = false
      if (!result.ok) netError = result.error || "mount failed"
      if (onDone) onDone(result)
      if (result.ok) run(["xdg-open", result.mounted_path || ""])
    }, true, 120000)
  }

  function netUnmount(url) {
    run([script("driveway"), "netmap", "unmount", url], function(result) {
      if (!result.ok) netError = result.error || "unmount failed"
    })
  }

  function netForget(id) {
    run([script("driveway"), "netmap", "forget", id], function() {})
  }

  // ---- cloud add wizard ------------------------------------------------------

  function cloudWizardStart(providerKey, label) {
    cloudWizard = { state: "picking", provider: providerKey, label: label }
  }

  function cloudWizardCancel() {
    cloudWizard = { state: "idle", provider: "", label: "" }
  }

  // OAuth providers: browser opens; process waits for sign-in (up to 5 min).
  // Non-OAuth (nextcloud/webdav/sftp/ftp/s3): direct add with credentials.
  function cloudWizardAdd(name, extras) {
    var prov = null
    for (var i = 0; i < cloudProviders.length; i++)
      if (cloudProviders[i].key === cloudWizard.provider) prov = cloudProviders[i]
    var oauth = prov ? !!prov.oauth
      : ["gdrive", "onedrive", "dropbox", "box", "pcloud"].indexOf(cloudWizard.provider) >= 0
    var cmd = oauth
      ? [script("driveway"), "cloud", "add-oauth", name, cloudWizard.provider]
      : [script("driveway"), "cloud", "add", name, cloudWizard.provider]
    cloudWizard = Object.assign({}, cloudWizard, {
      state: "working", phase: oauth ? "waiting for browser sign-in…" : "adding…",
      error: "" })
    runWithStdin(cmd, JSON.stringify(extras || {}), function(result) {
      if (result.ok) {
        cloudWizard = Object.assign({}, cloudWizard, { state: "done" })
        refreshCloud()
      } else {
        cloudWizard = Object.assign({}, cloudWizard, {
          state: "error", error: result.error || "add failed" })
      }
    }, true, 330000)
  }

  function cloudRemove(name) {
    run([script("driveway"), "cloud", "remove", name], function(result) {
      if (!result.ok) root.lastError = result.error || "remove failed"
      refreshCloud()
    })
  }


  function cloudUnmount(name) {
    run([script("driveway"), "cloud", "unmount", name], function(result) {
      if (!result.ok) root.lastError = result.message || "unmount failed"
      root.refreshCloud()
    })
  }

  function addCloudRemote() {
    run(["omarchy-launch-floating-terminal-with-presentation", "rclone config"])
  }

  // Short-lived process; `done(result)` gets the JSON line the CLI prints.
  // quiet=true: don't trigger the full refresh on exit (caller refreshes).
  function run(cmd, done, quiet) {
    var p = actionProcess.createObject(root, { command: cmd, done: done || null,
                                                quiet: !!quiet })
    p.running = true
  }

  // Same, but writes one JSON line to the child's stdin after start —
  // the secret-carrying channel (never argv). stdinEnabled is required
  // for Process.write() per Quickshell's Io API.
  function runWithStdin(cmd, stdinLine, done, quiet, timeoutMs) {
    var p = stdinProcess.createObject(root, { command: cmd, done: done || null,
                                              quiet: !!quiet,
                                              stdinLine: stdinLine,
                                              deadline: timeoutMs || 30000 })
    p.startWizardStep()
  }

  Component {
    id: actionProcess
    Process {
      property var done: null
      property bool quiet: false
      stdout: StdioCollector { id: out }
      onExited: {
        if (done) {
          var result = { status: "error", message: "" }
          try { result = JSON.parse(out.text.trim().split("\n").pop()) } catch (e) {}
          done(result)
        }
        if (!quiet) root.refresh()
        destroy()
      }
    }
  }

  Component {
    id: stdinProcess
    // Process is a QProcess: it takes no QML children, so the watchdog
    // Timer lives beside it under an Item wrapper.
    Item {
      id: step
      property var command: []
      property var done: null
      property bool quiet: false
      property string stdinLine: ""
      property real deadline: 30000

      function startWizardStep() { proc.running = true }

      width: 0; height: 0

      Process {
        id: proc
        command: step.command
        stdinEnabled: true
        stdout: StdioCollector { id: sout }
        onStarted: write(step.stdinLine + "\n")
        onExited: function(exitCode, exitStatus) {
          if (step.done) {
            var result = { ok: false, error: "no output" }
            try { result = JSON.parse(sout.text.trim().split("\n").pop()) } catch (e) {}
            step.done(result)
          }
          if (!step.quiet) root.refresh()
          step.destroy()
        }
      }

      Timer {
        interval: step.deadline
        running: proc.running
        onTriggered: {
          console.warn("gdeyoung.driveway: wizard step timed out")
          proc.running = false
        }
      }
    }
  }

  Component.onCompleted: refresh()
  Component.onDestruction: if (monitor.running) monitor.running = false
}

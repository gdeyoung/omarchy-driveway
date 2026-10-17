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
  property var busy: ({})          // drive.key -> {message, procs, uploads}
  property string lastError: ""

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
  function run(cmd, done) {
    var p = actionProcess.createObject(root, { command: cmd, done: done || null })
    p.running = true
  }

  Component {
    id: actionProcess
    Process {
      property var done: null
      stdout: StdioCollector { id: out }
      onExited: {
        if (done) {
          var result = { status: "error", message: "" }
          try { result = JSON.parse(out.text.trim().split("\n").pop()) } catch (e) {}
          done(result)
        }
        root.refresh()
        destroy()
      }
    }
  }

  Component.onCompleted: refresh()
  Component.onDestruction: if (monitor.running) monitor.running = false
}

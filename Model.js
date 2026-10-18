// Pure helpers for gdeyoung.driveway. Imported from Service.qml /
// Panel.qml as `import "Model.js" as Model`, ES5-only so the same file
// runs under node (tests/test_model.mjs).
//
// Core drive helpers vendored from jgarza9788/drives Model.js @ 255609e
// (MIT) — see NOTICE.md. Driveway additions: system kind, cloud state
// labels, drive filtering, bar aggregation.

var DEFAULT_ICONS = {
  system: "󰇅",              // md-laptop (the disk hosting /)
  thumb: "\u{f129e}",     // md-usb_flash_drive
  external: "\u{f02ca}",  // md-harddisk
  internal: "\uf0a0",     // fa-hdd
  sd: "\u{f07dc}",        // md-sd
  optical: "\u{f05ee}",   // md-disc
  image: "\u{f0a23}",     // md-zip_disk
  network: "\u{f048d}",   // md-server_network
  gdrive: "\u{f02b6}",    // md-google_drive
  onedrive: "\u{f03ca}",  // md-microsoft_onedrive
  dropbox: "\u{f01e3}",   // md-dropbox
  cloud: "\u{f015f}"      // md-cloud
}

var KIND_NAMES = {
  system: "System disk",
  thumb: "Thumb drive",
  external: "External drive",
  internal: "Internal drive",
  sd: "SD card",
  optical: "Disc",
  image: "Disk image",
  network: "Network share",
  gdrive: "Google Drive",
  onedrive: "OneDrive",
  dropbox: "Dropbox",
  cloud: "Cloud drive"
}

var CLOUD_STATE_LABELS = {
  mounted: "Mounted",
  starting: "Starting…",
  stopped: "Stopped",
  failed: "Failed · retrying",
  external: "Mounted (no unit)",
  idle: "Ready to mount",
  unknown: "Unknown"
}

// States that should turn things urgent (bar icon, row chip).
var CLOUD_URGENT = { failed: true }

function kindIcon(drive, icons) {
  var kind = drive && drive.kind ? drive.kind : "internal"
  var custom = icons ? icons[kind] : ""
  if (custom) return String(custom)
  return DEFAULT_ICONS[kind] || DEFAULT_ICONS.internal
}

function kindName(drive) {
  return KIND_NAMES[drive && drive.kind] || "Drive"
}

function cloudStateLabel(state) {
  return CLOUD_STATE_LABELS[state] || "Unknown"
}

function cloudUrgent(state) {
  return !!CLOUD_URGENT[state]
}

function humanBytes(n) {
  n = Number(n) || 0
  var units = ["B", "K", "M", "G", "T", "P"]
  var i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return (n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)) + units[i]
}

// "14.5G / 116G  13%", or "" when the size is unknown (gvfs cloud mounts).
function usageText(drive) {
  if (!drive || !(drive.size > 0)) return ""
  return humanBytes(drive.used) + " / " + humanBytes(drive.size) + "  " + drive.pct + "%"
}

// Account quota from `rclone about`: "14.5G / 2T  1%", or "" when unknown
// (backend has no quota, or the reading errored).
function aboutText(about) {
  if (!about || !(about.total > 0) || about.error) return ""
  var pct = Math.min(100, Math.round(100 * (about.used || 0) / about.total))
  return humanBytes(about.used || 0) + " / " + humanBytes(about.total) + "  " + pct + "%"
}

function aboutPct(about) {
  if (!about || !(about.total > 0) || about.error) return 0
  return Math.min(100, Math.round(100 * (about.used || 0) / about.total))
}

function groupDigits(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ",")
}

// [label, value] rows for the Info panel; empty values are dropped.
function infoRows(drive) {
  if (!drive) return []
  var fs = [drive.fstype, drive.fsver].filter(function(s) { return !!s }).join(" ")
  var model = [drive.vendor, drive.model].filter(function(s) { return !!s }).join(" ")
  var device = drive.path && drive.disk && drive.disk !== drive.path
    ? drive.path + " on " + drive.disk : drive.path
  var crypt = ""
  if (drive.encrypted) crypt = "LUKS · " + (drive.locked ? "locked" : "unlocked") +
    (drive.luksPath && drive.luksPath !== drive.path ? " (" + drive.luksPath + ")" : "")
  var rows = [
    ["Type", kindName(drive)],
    ["Device", device],
    ["Filesystem", fs],
    ["UUID", drive.uuid],
    ["Model", model],
    ["Serial", drive.serial],
    ["Connection", drive.connection],
    ["Encryption", crypt],
    ["Access", drive.mounted ? (drive.readOnly ? "Read-only" : "Read-write") : ""],
    ["Size", drive.size > 0 ? humanBytes(drive.size) + " (" + groupDigits(drive.size) + " bytes)" : ""],
    ["Mounted at", drive.mounted ? drive.mountpoint : ""]
  ]
  return rows.filter(function(r) { return !!r[1] })
}

// Live filter over the drive list (label, name, device, mountpoint, kind).
function filterDrives(drives, query) {
  var q = String(query || "").trim().toLowerCase()
  if (!q) return drives || []
  var out = []
  var list = drives || []
  for (var i = 0; i < list.length; i++) {
    var d = list[i]
    var hay = [d.label, d.name, d.path, d.mountpoint, kindName(d)]
      .filter(function(s) { return !!s }).join(" ").toLowerCase()
    if (hay.indexOf(q) !== -1) out.push(d)
  }
  return out
}

// Bar icon verdict: worst health wins (rclone-bs RANK idea, small scale).
// Returns {urgent, dim, badge}: urgent = a cloud drive failed or a drive is
// at/over fullPct; dim = nothing mounted at all; badge = mounted count.
function netGlyph(scheme) {
  var glyphs = { smb: "󰅹", sftp: "󰣀", ftp: "󰢑", nfs: "󰛧", dav: "󰕮",
                 davs: "󰕮" }
  return glyphs[scheme] || "󰲂"
}

function barState(drives, cloudDrives, cloudOk, fullPct) {
  var state = { urgent: false, dim: true, badge: 0 }
  var list = drives || []
  for (var i = 0; i < list.length; i++) {
    var d = list[i]
    if (d.mounted) { state.dim = false; state.badge++ }
    if (d.mounted && d.size > 0 && d.pct >= fullPct) state.urgent = true
  }
  var clouds = cloudDrives || []
  for (var j = 0; j < clouds.length; j++) {
    if (clouds[j].state === "mounted" || clouds[j].state === "external") { state.dim = false; state.badge++ }
    if (cloudUrgent(clouds[j].state)) state.urgent = true
  }
  if (!cloudOk && clouds.length === 0) {
    // rclone missing with no remotes is not an error state for the bar.
  }
  return state
}

// Stable identity for Repeater diffing: same tooltip, same row.
function sameDrives(a, b) {
  if (!a || !b || a.length !== b.length) return false
  for (var i = 0; i < a.length; i++) {
    if (a[i].key !== b[i].key || a[i].pct !== b[i].pct ||
        a[i].mounted !== b[i].mounted || a[i].pending !== b[i].pending) return false
  }
  return true
}

if (typeof module !== "undefined") {
  module.exports = {
    DEFAULT_ICONS: DEFAULT_ICONS,
    KIND_NAMES: KIND_NAMES,
    CLOUD_STATE_LABELS: CLOUD_STATE_LABELS,
    kindIcon: kindIcon,
    kindName: kindName,
    cloudStateLabel: cloudStateLabel,
    cloudUrgent: cloudUrgent,
    humanBytes: humanBytes,
    usageText: usageText,
    aboutText: aboutText,
    aboutPct: aboutPct,
    infoRows: infoRows,
    filterDrives: filterDrives,
    barState: barState,
    groupDigits: groupDigits,
    sameDrives: sameDrives
  }
}

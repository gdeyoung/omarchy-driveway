// node --test tests/test_model.mjs
import { test } from "node:test"
import assert from "node:assert/strict"
import { createRequire } from "node:module"
const require = createRequire(import.meta.url)
const Model = require("../Model.js")

test("humanBytes", () => {
  assert.equal(Model.humanBytes(0), "0B")
  assert.equal(Model.humanBytes(1024), "1.0K")
  assert.equal(Model.humanBytes(15032385536), "14.0G")
  assert.equal(Model.humanBytes(64 * 1024 ** 3), "64.0G")
  assert.equal(Model.humanBytes(157286400), "150M")
})

test("usageText empty when size unknown", () => {
  assert.equal(Model.usageText({ size: 0, used: 0, pct: 0 }), "")
  assert.equal(Model.usageText({ size: 100, used: 50, pct: 50 }), "50B / 100B  50%")
})

test("kindName covers system", () => {
  assert.equal(Model.kindName({ kind: "system" }), "System disk")
  assert.equal(Model.kindName({ kind: "thumb" }), "Thumb drive")
  assert.equal(Model.kindName({}), "Drive")
})

test("cloud state labels and urgency", () => {
  assert.equal(Model.cloudStateLabel("mounted"), "Mounted")
  assert.equal(Model.cloudStateLabel("failed"), "Failed · retrying")
  assert.equal(Model.cloudStateLabel("bogus"), "Unknown")
  assert.equal(Model.cloudUrgent("failed"), true)
  assert.equal(Model.cloudUrgent("mounted"), false)
  assert.equal(Model.cloudUrgent("stopped"), false)
})

test("filterDrives matches label/name/device/mount/kind, case-insensitive", () => {
  const drives = [
    { key: "a", label: "KINGSTON", name: "sdb1", path: "/dev/sdb1", mountpoint: "/run/media/x/KINGSTON", kind: "thumb" },
    { key: "b", label: "photos", name: "nvme1n1p2", path: "/dev/nvme1n1p2", mountpoint: "/mnt/photos", kind: "internal" },
    { key: "/", label: "System", name: "System", path: "", mountpoint: "/", kind: "system" }
  ]
  assert.equal(Model.filterDrives(drives, "").length, 3)
  assert.equal(Model.filterDrives(drives, "kingston").length, 1)
  assert.equal(Model.filterDrives(drives, "sdb").length, 1)
  assert.equal(Model.filterDrives(drives, "photos").length, 1)
  assert.equal(Model.filterDrives(drives, "system disk").length, 1)  // kind name
  assert.equal(Model.filterDrives(drives, "zzz").length, 0)
})

test("barState: worst health wins", () => {
  const drives = [
    { mounted: true, size: 100, pct: 95 },   // full → urgent
    { mounted: true, size: 100, pct: 10 }
  ]
  let s = Model.barState(drives, [], true, 90)
  assert.equal(s.urgent, true)
  assert.equal(s.dim, false)
  assert.equal(s.badge, 2)

  s = Model.barState([], [{ state: "failed" }], true, 90)
  assert.equal(s.urgent, true)
  assert.equal(s.dim, true)   // failed remote is not a mounted thing

  s = Model.barState([{ mounted: false }], [{ state: "mounted" }], true, 90)
  assert.equal(s.dim, false)
  assert.equal(s.badge, 1)

  s = Model.barState([], [], false, 90)
  assert.equal(s.dim, true)
  assert.equal(s.urgent, false)
})

test("sameDrives identity", () => {
  const a = [{ key: "x", pct: 10, mounted: true, pending: -1 }]
  const b = [{ key: "x", pct: 10, mounted: true, pending: -1 }]
  const c = [{ key: "x", pct: 11, mounted: true, pending: -1 }]
  assert.equal(Model.sameDrives(a, b), true)
  assert.equal(Model.sameDrives(a, c), false)
})

test("infoRows drops empty values, includes usage size", () => {
  const rows = Model.infoRows({ kind: "thumb", path: "/dev/sdb1", disk: "/dev/sdb",
    fstype: "exfat", size: 64003604480, label: "KINGSTON", mounted: true,
    readOnly: false, mountpoint: "/run/media/x/KINGSTON" })
  const keys = rows.map(r => r[0])
  assert.ok(keys.includes("Type"))
  assert.ok(keys.includes("Size"))
  assert.ok(!keys.includes("UUID"))       // empty → dropped
  assert.ok(!keys.includes("Encryption"))
})

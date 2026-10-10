import QtQuick
import Quickshell
import Quickshell.Io
import "Effects.js" as Fx

// The front end's only link to the hardware: the mothership CLI, which talks to mothershipd.
// Holds the last status, applies changes optimistically and queues commands one at a time.
QtObject {
  id: ship

  // Command prefix (argv). Empty: the mothership-cli wrapper next to this file.
  property var command: []
  property bool fast: false          // poll every 2 s instead of 10 s (popup or window open)

  property var status: ({})
  property bool loaded: false
  property bool daemonUp: true
  property string error: ""
  property int generation: 0         // bumps with every change, so stale polls are dropped

  readonly property var config: status.config || {}
  readonly property var kb: config.keyboard || ({ effect: "off" })
  readonly property var ch: config.chassis || ({ effect: "off" })
  readonly property var thermal: status.thermal || {}
  readonly property var powerSaved: config.power_button || {}
  readonly property bool hasKeyboard: !!(status.devices && status.devices.keyboard)
  readonly property bool hasChassis: !!(status.devices && status.devices.chassis)
  readonly property bool hasThermal: thermal.available === true
  readonly property string mode: thermal.mode || ""
  readonly property bool gmode: mode === "performance"
  readonly property bool auto: (config.thermal || {}).auto !== false
  readonly property var fans: thermal.fans || []

  // The daemon's own problems with each part, in plain words with the fix.
  // What the hardware has. Older daemons don't say: then assume every zone and every key lights.
  readonly property var chassisZones: status.chassis && status.chassis.zones ? status.chassis.zones : null
  function hasZone(z) {
    var zs = chassisZones
    if (!zs) return true
    if (z === "rear") return zs.indexOf("rear") >= 0 || zs.indexOf("rear_left") >= 0 || zs.indexOf("rear_right") >= 0
    return zs.indexOf(z) >= 0
  }
  readonly property bool hasTouchpad: hasZone("touchpad")
  readonly property bool hasHead: hasZone("head")
  readonly property bool hasRear: hasZone("rear")
  readonly property var unlit: status.keyboard && status.keyboard.unlit ? status.keyboard.unlit.map(Number) : []
  readonly property bool chassisOk: !(status.errors || {}).chassis
  readonly property var problems: {
    var e = status.errors || {}, out = [], denied = []
    var names = { keyboard: "Keyboard lights", chassis: "Chassis lights", thermal: "Thermal control", run: "Fire effect" }
    for (var part in e) {
      var msg = String(e[part] || "")
      var name = names[part] || part
      if (/permission denied/i.test(msg)) denied.push(name)
      else out.push(name + ": " + msg.replace(/^\[Errno \d+\]\s*/, ""))
    }
    if (denied.length) {
      var who = denied.length > 1 ? denied.slice(0, -1).join(", ") + " and " + denied[denied.length - 1].toLowerCase() : denied[0]
      out.unshift(who + (denied.length > 1 ? " need" : " needs") + " permission: log out and back in after installing mothership (udev rule and mothership group).")
    }
    return out
  }
  readonly property real boostPct: fans.length ? (fans[0].boost_pct || 0) : 0

  readonly property string pluginDir: {
    var u = String(Qt.resolvedUrl("."))
    return decodeURIComponent(u.replace(/^file:\/\//, "")).replace(/\/$/, "")
  }
  readonly property var argv0: command && command.length ? command : ["sh", pluginDir + "/mothership-cli"]

  function cli(args) { return argv0.concat(["--json"]).concat(args) }

  // ---- polling
  property int _pollGen: 0
  property Timer pollTimer: Timer {
    interval: ship.fast ? 2000 : 10000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: ship.refresh()
  }

  function refresh() {
    if (statusProc.running) return
    _pollGen = generation
    statusProc.command = cli(["status"])
    statusProc.running = true
  }

  property Process statusProc: Process {
    stdout: StdioCollector { id: statusOut; waitForEnd: true }
    stderr: StdioCollector { id: statusErr; waitForEnd: true }
    onExited: function(code) {
      if (code !== 0) {
        ship.fail(code, statusErr.text)
        return
      }
      if (ship._pollGen !== ship.generation || ship.queue.length || ship.runner.running) return
      try {
        var wasDown = !ship.daemonUp
        ship.status = JSON.parse(statusOut.text)
        ship.loaded = true
        ship.daemonUp = true
        if (wasDown) ship.error = ""
      } catch (e) {
        ship.error = "mothership sent something that isn't JSON. Check `mothership --json status`."
      }
    }
  }

  function fail(code, text) {
    var msg = String(text || "").trim().replace(/^mothership:\s*/, "")
    if (msg.indexOf("isn't running") >= 0 || msg.indexOf("is not running") >= 0) {
      daemonUp = false
      error = "mothershipd isn't running: systemctl --user start mothershipd"
    } else if (code === 127) {
      daemonUp = false
      error = "mothership isn't installed. Install the package, or set this widget's command."
    } else {
      error = msg || ("mothership failed (exit " + code + ")")
    }
  }

  // ---- commands
  property var queue: []
  property var _current: null

  // key: commands with the same key replace one another while queued (sliders, painting).
  function run(args, key, done) {
    generation++
    var q = queue.slice()
    if (key) q = q.filter(function(c) { return c.key !== key })
    q.push({ args: args, key: key || "", done: done || null })
    queue = q
    pump()
  }

  function pump() {
    if (runner.running || !queue.length) return
    var q = queue.slice()
    _current = q.shift()
    queue = q
    runner.command = cli(_current.args)
    runner.running = true
  }

  property Process runner: Process {
    stdout: StdioCollector { id: runOut; waitForEnd: true }
    stderr: StdioCollector { id: runErr; waitForEnd: true }
    onExited: function(code) {
      var cur = ship._current
      ship._current = null
      var result = null
      if (code === 0) {
        ship.error = ""
        ship.daemonUp = true
        try { result = JSON.parse(runOut.text) } catch (e) { result = null }
      } else {
        ship.fail(code, runErr.text)
      }
      if (cur && cur.done) cur.done(code === 0, result)
      if (ship.queue.length) ship.pump()
      else { ship.generation++; ship.refresh() }
    }
  }

  // Optimistic local change: patch(section, values) merges into status.config[section].
  function patch(section, values) {
    var s = JSON.parse(JSON.stringify(status || {}))
    s.config = s.config || {}
    s.config[section] = Object.assign({}, s.config[section] || {}, values)
    status = s
  }

  function patchThermal(values) {
    var s = JSON.parse(JSON.stringify(status || {}))
    s.thermal = Object.assign({}, s.thermal || {}, values)
    status = s
  }

  // ---- keyboard
  readonly property var kbEffects: ["static", "breathing", "wave", "spectrum", "scanner", "aurora", "gradient", "static-blue", "fire", "perkey", "off"]
  readonly property var colorEffects: ["static", "breathing", "scanner", "gradient"]
  readonly property bool reactive: kb.on === "press" || kb.on === "release"

  function kbColor() { return (kb.colors && kb.colors[0]) || "ff2000" }
  // The colours an effect gets: gradient needs two, so a lone colour gets a neighbour hue.
  function kbColors(name) {
    var c = (kb.colors || []).slice(0, 2)
    if (!c.length) c = [kbColor()]
    if ((name || kb.effect) === "gradient" && c.length < 2) c.push(Fx.toHex(Fx.hsv(Fx.hueOf(Fx.parseHex(c[0])) + 0.25, 1, 1)))
    return c
  }

  function setEffect(name) {
    if (kbEffects.indexOf(name) < 0) return "unknown effect: " + name
    if (name === "fire" || name === "off") {
      patch("keyboard", { effect: name, on: "static" })
      run(["kb", name === "fire" ? "fire" : "off"], "kb.effect")
      return "ok"
    }
    if (name === "perkey") {
      patch("keyboard", { effect: "perkey" })
      var keys = kb.keys || {}
      var first = Object.keys(keys)[0]
      // Re-send one stored key: the daemon then shows every stored key again.
      run(["kb", "key", (first !== undefined ? first : "0") + "=" + (first !== undefined ? keys[first] : kbColor())], "kb.effect")
      return "ok"
    }
    var on = reactive ? kb.on : "static"
    patch("keyboard", { effect: name, on: on })
    var args = ["kb", "effect", name, "--on", on]
    if (colorEffects.indexOf(name) >= 0) {
      var cols = kbColors(name)
      for (var i = 0; i < cols.length; i++) args.push("-c", cols[i])
      patch("keyboard", { colors: cols })
    }
    if (name !== "static" && name !== "static-blue") args.push("--speed", String(kb.speed === undefined ? 1 : kb.speed))
    if (name === "wave" && kb.direction) args.push("--dir", kb.direction)
    run(args, "kb.effect")
    return "ok"
  }

  // A colour applies to the current effect when it takes colours, else switches to static.
  function setColor(hex) {
    hex = String(hex || "").replace(/^#/, "").toLowerCase()
    if (!/^[0-9a-f]{6}$/.test(hex)) return "colour is RRGGBB"
    var eff = colorEffects.indexOf(kb.effect) >= 0 ? kb.effect : "static"
    var on = reactive ? kb.on : "static"
    patch("keyboard", { effect: eff, colors: [hex], on: on })
    run(["kb", "effect", eff, "-c", hex, "--on", on].concat(eff === "static" ? [] : ["--speed", String(kb.speed === undefined ? 1 : kb.speed)]), "kb.effect")
    return "ok"
  }

  function setSpeed(v) {
    patch("keyboard", { speed: v })
    var eff = kb.effect
    if (["breathing", "wave", "spectrum", "scanner", "aurora"].indexOf(eff) < 0) return "ok"
    var args = ["kb", "effect", eff, "--speed", String(v), "--on", reactive ? kb.on : "static"]
    if (colorEffects.indexOf(eff) >= 0) (kb.colors || []).slice(0, 2).forEach(function(c) { args.push("-c", c) })
    if (eff === "wave" && kb.direction) args.push("--dir", kb.direction)
    run(args, "kb.effect")
    return "ok"
  }

  function setDirection(d) {
    patch("keyboard", { direction: d })
    if (kb.effect === "wave") run(["kb", "effect", "wave", "--dir", d, "--speed", String(kb.speed === undefined ? 1 : kb.speed), "--on", reactive ? kb.on : "static"], "kb.effect")
    return "ok"
  }

  function setBrightness(n) {
    n = Math.max(0, Math.min(100, Math.round(n)))
    patch("keyboard", { brightness: n })
    run(["kb", "brightness", String(n)], "kb.brightness")
    return "ok"
  }

  // Light keys as I type (firmware key-press mode) on top of the current firmware effect.
  function setReactive(on) {
    var eff = kb.effect
    if (["fire", "off", "perkey"].indexOf(eff) >= 0) eff = "static"
    patch("keyboard", { effect: eff, on: on ? "press" : "static" })
    if (eff === "static" && on) { run(["kb", "reactive", kbColor()], "kb.effect"); return "ok" }
    var args = ["kb", "effect", eff, "--on", on ? "press" : "static"]
    if (colorEffects.indexOf(eff) >= 0) (kb.colors || [kbColor()]).slice(0, 2).forEach(function(c) { args.push("-c", c) })
    if (eff !== "static") args.push("--speed", String(kb.speed === undefined ? 1 : kb.speed))
    run(args, "kb.effect")
    return "ok"
  }

  // Paint keys: {led: "rrggbb"}. Batches merge until the previous batch has gone out.
  property var _paint: ({})
  function paintKeys(map) {
    var clean = {}
    for (var l in map) if (unlit.indexOf(Number(l)) < 0) clean[l] = map[l]
    map = clean
    if (!Object.keys(map).length) return
    var keys = Object.assign({}, kb.keys || {}, map)
    patch("keyboard", { effect: "perkey", keys: keys })
    var p = Object.assign({}, _paint, map)
    _paint = p
    paintTimer.restart()
  }
  property Timer paintTimer: Timer {
    interval: 90
    onTriggered: {
      if (ship.runner.running) { restart(); return }
      var p = ship._paint
      ship._paint = {}
      var args = ["kb", "key"]
      for (var led in p) args.push(led + "=" + p[led])
      if (args.length > 2) ship.run(args)
    }
  }

  // ---- chassis
  readonly property var chEffects: ["static", "breathing", "pulse", "morph", "spectrum", "wave", "off"]

  function chassisZone(zone, hex) {
    hex = String(hex || "").replace(/^#/, "").toLowerCase()
    if (!/^[0-9a-f]{6}$/.test(hex)) return "colour is RRGGBB"
    var zones = Object.assign({}, ch.zones || {})
    if (zone === "all") { zones = {}; patch("chassis", { effect: "static", zones: zones, colors: [hex] }) }
    else { zones[zone] = hex; patch("chassis", { effect: "static", zones: zones }) }
    run(["chassis", "color", zone, hex], "ch.color." + zone)
    return "ok"
  }

  function chassisEffect(name, hex) {
    if (chEffects.indexOf(name) < 0) return "unknown chassis effect: " + name
    var args = ["chassis", "effect", name]
    var values = { effect: name }
    if (hex) { args.push("-c", hex); values.colors = [hex] }
    patch("chassis", values)
    run(args, "ch.effect")
    return "ok"
  }

  function chassisBrightness(n) {
    n = Math.max(0, Math.min(100, Math.round(n)))
    patch("chassis", { brightness: n })
    run(["chassis", "brightness", String(n)], "ch.brightness")
    return "ok"
  }

  // ---- thermal
  function setMode(name) {
    if ((thermal.modes || []).indexOf(name) < 0) return "unknown mode: " + name
    patchThermal({ mode: name })
    patch("thermal", { auto: false })
    run(["fans", "mode", name], "th.mode")
    return "ok"
  }

  function setAuto(on) {
    patch("thermal", { auto: !!on })
    run(["fans", "auto", on ? "on" : "off"], "th.auto")
    return "ok"
  }

  function setBoost(pct) {
    pct = Math.max(0, Math.min(100, Math.round(pct)))
    patchThermal({ fans: fans.map(function(f) { return Object.assign({}, f, { boost_pct: pct }) }) })
    patch("thermal", { auto: false })
    run(["fans", "boost", String(pct)], "th.boost")
    return "ok"
  }

  // CPU temperature limit: throttle 0-15 °C earlier.
  // null hides the control: no int340x driver, or the BIOS locked the TCC offset
  readonly property var tcc: (thermal.tcc_offset === undefined || thermal.tcc_locked) ? null : thermal.tcc_offset
  function setTcc(n) {
    n = Math.max(0, Math.min(15, Math.round(n)))
    patchThermal({ tcc_offset: n })
    patch("thermal", { tcc_offset: n })
    run(["fans", "tcc", String(n)], "th.tcc")
    return "ok"
  }

  // CPU package power limit, per thermal mode ("all" for every mode); null clears it.
  readonly property var powerLimits: (config.thermal || {}).power_limits || ({})
  readonly property var powerNow: thermal.power_limits || null
  function setPowerLimit(watts, forMode) {
    var key = forMode || "all"
    var limits = Object.assign({}, powerLimits)
    if (watts === null || watts === undefined) delete limits[key]
    else limits[key] = Math.round(watts)
    patch("thermal", { power_limits: limits })
    var args = ["fans", "power-limit", watts === null || watts === undefined ? "off" : String(Math.round(watts))]
    if (forMode) args.push("--mode", forMode)
    run(args, "th.power." + key)
    return "ok"
  }

  // Graphics mode: shown from the panel's GPU; changing it means restarting into firmware setup.
  readonly property var graphics: status.graphics || null
  function restartToSetup() {
    run(["graphics", "change", "--yes"], "graphics")
    return "ok"
  }

  function toggleGmode() {
    patchThermal({ mode: gmode ? "balanced" : "performance" })
    patch("thermal", { auto: false })
    run(["gmode", "toggle"], "th.mode")
    return "ok"
  }

  // ---- power button (writes the lighting controller's flash; only after an explicit confirm)
  function savePower(drafts, done) {
    var states = Object.keys(drafts)
    var left = states.length, ok = true
    if (!left) { if (done) done(true); return }
    states.forEach(function(st) {
      run(["power", "set", st, drafts[st], "--write-flash"], "", function(success) {
        ok = ok && success
        if (--left === 0 && done) done(ok)
      })
    })
  }
}

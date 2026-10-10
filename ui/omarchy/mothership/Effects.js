.pragma library
// Client-side approximations of the lighting effects, so the mirror shows what the machine is
// doing without asking the hardware. Colours are [r, g, b] in 0..255 and an intensity 0..1.

function parseHex(s, fallback) {
  var t = String(s || "").replace(/^#/, "")
  if (!/^[0-9a-fA-F]{6}$/.test(t)) return fallback || [255, 255, 255]
  return [parseInt(t.substr(0, 2), 16), parseInt(t.substr(2, 2), 16), parseInt(t.substr(4, 2), 16)]
}

function toHex(rgb) {
  function h(v) { var s = Math.max(0, Math.min(255, Math.round(v))).toString(16); return s.length < 2 ? "0" + s : s }
  return h(rgb[0]) + h(rgb[1]) + h(rgb[2])
}

function hsv(h, s, v) {
  h = ((h % 1) + 1) % 1
  var i = Math.floor(h * 6), f = h * 6 - i
  var p = v * (1 - s), q = v * (1 - f * s), t = v * (1 - (1 - f) * s)
  var r, g, b
  switch (i % 6) {
    case 0: r = v; g = t; b = p; break
    case 1: r = q; g = v; b = p; break
    case 2: r = p; g = v; b = t; break
    case 3: r = p; g = q; b = v; break
    case 4: r = t; g = p; b = v; break
    default: r = v; g = p; b = q
  }
  return [r * 255, g * 255, b * 255]
}

function hueOf(rgb) {
  var r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255
  var mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn
  if (d === 0) return 0
  var h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4
  return ((h / 6) + 1) % 1
}

function mix(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]
}

function frac(x) { return x - Math.floor(x) }
function tri(x) { var f = frac(x); return f < 0.5 ? f * 2 : 2 - f * 2 }
function hash(a, b) { return frac(Math.sin(a * 127.1 + b * 311.7) * 43758.5453) }

var SPEED = [0.6, 1.0, 1.7]

// Which effects change over time (the mirror only ticks for these).
function animated(kb) {
  if (!kb) return false
  if (kb.on === "press" || kb.on === "release") return true
  return ["breathing", "wave", "spectrum", "scanner", "aurora", "fire"].indexOf(kb.effect) >= 0
}

function chassisAnimated(ch) {
  return !!ch && ["breathing", "pulse", "morph", "spectrum", "wave"].indexOf(ch.effect) >= 0
}

// Fire's heat ramp: black, ember red, orange, yellow.
function heatColor(h) {
  h = Math.max(0, Math.min(1, h))
  if (h < 0.35) return mix([0, 0, 0], [170, 12, 0], h / 0.35)
  if (h < 0.7) return mix([170, 12, 0], [255, 90, 0], (h - 0.35) / 0.35)
  return mix([255, 90, 0], [255, 200, 40], (h - 0.7) / 0.3)
}

// One key: nx 0..1 left to right, ny 0..1 top (F-keys) to bottom (Space). Returns {c, i}.
function keyColor(kb, led, nx, ny, t, overrides) {
  var eff = kb.effect || "static"
  var cols = (kb.colors || []).map(function(c) { return parseHex(c) })
  var c1 = cols[0] || [255, 32, 0], c2 = cols[1] || c1
  var sp = SPEED[kb.speed] || 1
  var bri = Math.max(0, Math.min(100, kb.brightness === undefined ? 100 : kb.brightness)) / 100
  var out
  if (overrides && overrides[led] !== undefined) {
    out = { c: parseHex(overrides[led]), i: 1 }
  } else if (eff === "off") {
    return { c: [0, 0, 0], i: 0 }
  } else if (eff === "static-blue") {
    out = { c: [0, 255, 255], i: 1 }
  } else if (eff === "perkey") {
    var k = kb.keys || {}
    out = { c: parseHex(k[String(led)], c1), i: 1 }
  } else if (eff === "breathing") {
    var ph = t * sp / 4
    var lv = 0.5 - 0.5 * Math.cos(2 * Math.PI * ph)
    out = { c: Math.floor(ph) % 2 ? c2 : c1, i: 0.04 + 0.96 * lv }
  } else if (eff === "spectrum") {
    out = { c: hsv(t * sp / 6, 1, 1), i: 1 }
  } else if (eff === "wave") {
    var pos
    switch (kb.direction) {
      case "left": pos = -nx; break
      case "up": pos = -ny * 0.6; break
      case "down": pos = ny * 0.6; break
      case "bounce": pos = tri(nx * 0.5 + t * sp * 0.1) * 0.8; break
      case "bounce-v": pos = tri(ny * 0.5 + t * sp * 0.1) * 0.8; break
      default: pos = nx
    }
    out = { c: hsv(pos - t * sp * 0.35, 1, 1), i: 1 }
  } else if (eff === "scanner") {
    var band = tri(t * sp / 2.6) * 1.1 - 0.05
    var d = Math.abs(nx - band)
    var lit = Math.pow(Math.max(0, 1 - d / 0.14), 1.4)
    out = cols.length > 1 ? { c: mix(c2, c1, lit), i: 0.25 + 0.75 * lit } : { c: c1, i: 0.03 + 0.97 * lit }
  } else if (eff === "aurora") {
    var w = Math.sin(nx * 5.2 + t * sp * 0.45) * 0.5 + Math.sin(ny * 3.1 - t * sp * 0.3 + nx * 2) * 0.5
    var hue = 0.36 + 0.22 * (w * 0.5 + 0.5)
    out = { c: hsv(hue, 0.9, 1), i: 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(t * sp * 0.8 + nx * 7)) }
  } else if (eff === "gradient") {
    var b = cols.length > 1 ? c2 : hsv(hueOf(c1) + 0.25, 1, 1)
    out = { c: mix(c1, b, nx), i: 1 }
  } else if (eff === "fire") {
    var seed = hash(led, 1.7)
    var n = 0.5 + 0.28 * Math.sin(t * (6.1 + seed * 3) + seed * 12.9)
              + 0.22 * Math.sin(t * 2.7 + seed * 4.1 - ny * 5.0)
    var tongue = 0.12 * Math.sin(nx * 9.0 + t * 1.9) + 0.08 * Math.sin(nx * 17.0 - t * 3.1)
    var heat = Math.pow(ny, 1.25) * 0.95 + (n - 0.5) * 0.5 + tongue - 0.06
    var hc = heatColor(heat)
    out = { c: hc, i: Math.max(0.0, Math.min(1, heat * 1.35)) }
  } else {
    out = { c: c1, i: 1 }
  }
  // Light keys as I type: the effect only shows where (simulated) keys were just pressed.
  if ((kb.on === "press" || kb.on === "release") && eff !== "fire" && !(overrides && overrides[led] !== undefined)) {
    var rate = 3, slot = Math.floor(t * rate), glow = 0
    for (var s = slot; s > slot - 4; s--) {
      if (hash(led, s) < 0.045) glow = Math.max(glow, Math.exp(-(t * rate - s) * 1.3))
    }
    out.i *= glow
  }
  out.i *= bri
  return out
}

var RAINBOW = [[255, 0, 0], [255, 165, 0], [255, 255, 0], [0, 128, 0], [0, 191, 255], [0, 0, 255], [128, 0, 128]]

function rainbowAt(p) {
  p = frac(p) * RAINBOW.length
  var i = Math.floor(p)
  return mix(RAINBOW[i], RAINBOW[(i + 1) % RAINBOW.length], p - i)
}

// A chassis zone ("head", "rear", "touchpad", "power"); nx places it for travelling effects.
function zoneColor(ch, zone, nx, t) {
  var eff = ch.effect || "static"
  var cols = (ch.colors || []).map(function(c) { return parseHex(c) })
  var c1 = cols[0] || [0, 240, 240]
  var dur = Math.max(300, ch.duration_ms || 3000) / 1000
  var bri = Math.max(0, Math.min(100, ch.brightness === undefined ? 100 : ch.brightness)) / 100
  var out
  if (eff === "off") return { c: [0, 0, 0], i: 0 }
  if (eff === "static") {
    var z = ch.zones || {}
    var hex = z[zone] || (zone === "rear_left" || zone === "rear_right" ? z.rear : undefined)
    out = { c: hex ? parseHex(hex) : c1, i: 1 }
  } else if (eff === "breathing") {
    out = { c: c1, i: 0.5 - 0.5 * Math.cos(2 * Math.PI * t / dur) }
  } else if (eff === "pulse") {
    var p = frac(t / dur)
    out = { c: c1, i: p < 0.15 ? p / 0.15 : Math.exp(-(p - 0.15) * 5) }
  } else if (eff === "morph") {
    var seq = cols.length > 1 ? cols : [c1, [0, 0, 0]]
    var q = frac(t / dur) * seq.length, k = Math.floor(q)
    out = { c: mix(seq[k], seq[(k + 1) % seq.length], q - k), i: 1 }
  } else if (eff === "spectrum") {
    out = { c: rainbowAt(t / dur), i: 1 }
  } else if (eff === "wave") {
    out = { c: rainbowAt(t / dur - nx), i: 1 }
  } else {
    out = { c: c1, i: 1 }
  }
  out.i *= bri
  return out
}

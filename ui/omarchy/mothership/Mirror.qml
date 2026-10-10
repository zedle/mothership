import QtQuick
import qs.Commons
import "../../gage-ui" as G
import "KeyLayout.js" as Layout
import "Effects.js" as Fx
import "Icons.js" as Icons

// A live, to-scale mirror of the machine: the real key layout plus the chassis lights (rear
// loop, touchpad, alien head, power button), animating the current effects client-side.
// With `paintable`, clicking or dragging paints keys with `brush` and clicking a chassis zone
// colours it.
Item {
  id: root

  property var keyboard: ({})
  property var chassis: ({})
  property string powerColor: ""      // the power button's saved colour for the current state
  property bool showTouchpad: true    // the touchpad has lights (status chassis.zones)
  property bool showHead: true
  property bool showRear: true
  property var unlit: []              // LEDs that don't exist on this keyboard: outline only
  property bool chassisKnown: true    // false: the daemon can't drive the chassis lights, draw them dark
  property bool compact: true
  property bool live: true            // animate (only while shown)
  property bool paintable: false
  property string brush: "ff2000"
  property bool showLegends: !compact
  property var overrides: ({})        // keys painted here, shown before the daemon confirms
  property int hoverLed: -1
  property string hoverZone: ""

  signal keysPainted(var map)          // {led: "rrggbb"}
  signal zoneClicked(string zone)
  signal colorPicked(string hex)       // right-click on a key: pick up its colour
  signal clicked()

  property G.Theme theme: G.Theme {}

  // ---- geometry, in layout units (the keyboard is Layout.width units wide)
  readonly property real pad: 50
  readonly property real rearH: 12
  readonly property real keysY: rearH + 34
  readonly property real f0H: 34                       // F-key row is short
  readonly property real capH: 53
  readonly property real pitch: 63
  readonly property real keysH: f0H + 10 + 5 * pitch - 10
  readonly property real bottomY: keysY + keysH + 30
  readonly property real bottomH: compact ? 64 : 150
  readonly property real unitsW: Layout.width + pad * 2
  readonly property real unitsH: bottomY + bottomH + pad * 2
  readonly property real s: Math.min(width / unitsW, height / unitsH)
  readonly property real ox: (width - unitsW * s) / 2 + pad * s
  readonly property real oy: (height - unitsH * s) / 2 + pad * s

  implicitWidth: 440
  implicitHeight: width * unitsH / unitsW

  function rowY(r) { return r === 0 ? 0 : f0H + 10 + (r - 1) * pitch }
  function rowH(r) { return r === 0 ? f0H : capH }

  readonly property real tpW: compact ? 300 : 340
  readonly property var tpRect: ({ x: (Layout.width - tpW) / 2, y: bottomY, w: tpW, h: compact ? bottomH : bottomH - 40 })
  // The lid logo zone, drawn as a neutral glowing lozenge.
  readonly property var headRect: ({ x: 40, y: bottomY + (bottomH - (compact ? 22 : 30)) / 2, w: compact ? 74 : 104, h: compact ? 22 : 30 })
  readonly property var powerRect: ({ x: Layout.width - 30 - Math.min(bottomH, 64), y: bottomY + (bottomH - Math.min(bottomH, 64)) / 2, w: Math.min(bottomH, 64), h: Math.min(bottomH, 64) })
  readonly property var rearRect: ({ x: Layout.width * 0.06, y: 0, w: Layout.width * 0.88, h: rearH })

  // ---- colours from the theme (the lights themselves are data)
  readonly property color deck: theme.light ? Qt.tint(Color.foreground, Util.alpha(Color.background, 0.06)) : Util.alpha(Color.foreground, 0.035)
  readonly property color deckRim: theme.light ? Util.alpha(Color.foreground, 0.5) : theme.ink(0.08)
  readonly property color cap: theme.light ? Util.alpha(Color.background, 0.07) : Util.alpha(Color.foreground, 0.05)
  readonly property color capRim: theme.light ? Util.alpha(Color.background, 0.12) : theme.ink(0.07)
  readonly property color legend: theme.light ? Util.alpha(Color.background, 0.55) : Util.alpha(Color.foreground, 0.45)

  function css(c, a) {
    return "rgba(" + Math.round(c.r * 255) + "," + Math.round(c.g * 255) + "," + Math.round(c.b * 255) + "," + (a === undefined ? c.a : c.a * a) + ")"
  }
  function rgba(rgb, a) {
    return "rgba(" + Math.round(rgb[0]) + "," + Math.round(rgb[1]) + "," + Math.round(rgb[2]) + "," + Math.max(0, Math.min(1, a)) + ")"
  }

  readonly property bool animating: Fx.animated(keyboard) || Fx.chassisAnimated(chassis)
  readonly property real t0: Date.now()
  property real t: 0

  Timer {
    interval: 50
    repeat: true
    running: root.live && root.visible && root.animating && root.width > 0
    onTriggered: { root.t = (Date.now() - root.t0) / 1000; canvas.requestPaint() }
  }

  onKeyboardChanged: {
    // Painted keys the daemon now reports (or a switch away from per-key) end the override.
    var kb = keyboard || {}, ov = overrides || {}, keep = {}, n = 0
    if (kb.effect === "perkey") {
      var stored = kb.keys || {}
      for (var led in ov) if (stored[String(led)] !== ov[led]) { keep[led] = ov[led]; n++ }
    }
    if (n !== Object.keys(ov).length) overrides = keep
    canvas.requestPaint()
  }
  onChassisChanged: canvas.requestPaint()
  onOverridesChanged: canvas.requestPaint()
  onHoverLedChanged: canvas.requestPaint()
  onHoverZoneChanged: canvas.requestPaint()
  onPowerColorChanged: canvas.requestPaint()
  onWidthChanged: canvas.requestPaint()
  onHeightChanged: canvas.requestPaint()
  Connections {
    target: root.theme
    function onSwatchesChanged() { canvas.requestPaint() }
  }
  Connections {
    target: Color
    function onShellValuesChanged() { canvas.requestPaint() }
  }

  Canvas {
    id: canvas
    anchors.fill: parent
    renderStrategy: Canvas.Cooperative

    function rr(ctx, x, y, w, h, r) {
      ctx.beginPath()
      ctx.moveTo(x + r, y)
      ctx.arcTo(x + w, y, x + w, y + h, r)
      ctx.arcTo(x + w, y + h, x, y + h, r)
      ctx.arcTo(x, y + h, x, y, r)
      ctx.arcTo(x, y, x + w, y, r)
      ctx.closePath()
    }

    function glyph(ctx, name, x, y, size, style) {
      ctx.save()
      ctx.translate(x, y)
      ctx.scale(size / 256, size / 256)
      ctx.beginPath()
      ctx.path = Icons.paths[name] || ""
      ctx.fillStyle = style
      ctx.fill()
      ctx.restore()
    }

    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      ctx.clearRect(0, 0, width, height)
      if (root.s <= 0) return
      var t = root.t, kb = root.keyboard || {}, ch = root.chassis || {}
      if (!root.chassisKnown) ch = { effect: "off" }
      ctx.save()
      ctx.translate(root.ox, root.oy)
      ctx.scale(root.s, root.s)

      // Key colours first: they also tint the halo.
      var keys = Layout.keys
      var ov = root.overrides || {}
      var lcs = [], sr = 0, sg = 0, sb = 0, si = 0
      for (var j = 0; j < keys.length; j++) {
        var kk = keys[j]
        var c0 = root.unlit.indexOf(kk.led) >= 0 ? { c: [0, 0, 0], i: 0 }
               : Fx.keyColor(kb, kk.led, (kk.x + kk.w / 2) / Layout.width, kk.row / 5, t, ov)
        lcs.push(c0)
        sr += c0.c[0] * c0.i; sg += c0.c[1] * c0.i; sb += c0.c[2] * c0.i; si += c0.i
      }

      // A soft halo of the current light behind the machine.
      if (si > 0.5) {
        var avg = [sr / si, sg / si, sb / si], level = Math.min(1, si / keys.length * 1.4)
        var cx = Layout.width / 2, cy = (root.keysY + root.bottomY + root.bottomH) / 2
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1, 0.5)
        var halo = ctx.createRadialGradient(0, 0, 0, 0, 0, Layout.width * 0.62)
        halo.addColorStop(0, root.rgba(avg, (root.theme.light ? 0.22 : 0.3) * level))
        halo.addColorStop(0.6, root.rgba(avg, (root.theme.light ? 0.08 : 0.12) * level))
        halo.addColorStop(1, root.rgba(avg, 0))
        ctx.fillStyle = halo
        ctx.fillRect(-Layout.width * 0.7, -Layout.width * 0.7, Layout.width * 1.4, Layout.width * 1.4)
        ctx.restore()
      }

      // The machine's deck.
      // It reaches up to hold the rear lights, so they read on light themes too.
      var deckTop = root.compact ? -16 : -42
      rr(ctx, -root.pad * 0.7, deckTop, Layout.width + root.pad * 1.4, root.bottomY + root.bottomH + 18 - deckTop, 26)
      ctx.fillStyle = root.css(root.deck)
      ctx.fill()
      ctx.lineWidth = 1.5 / root.s
      ctx.strokeStyle = root.css(root.deckRim)
      ctx.stroke()

      // Rear light loop: two halves, glowing.
      var rr0 = root.rearRect
      var halves = [["rear_left", rr0.x, 0.25], ["rear_right", rr0.x + rr0.w / 2, 0.75]]
      for (var hI = 0; hI < 2; hI++) {
        var z = root.showRear ? Fx.zoneColor(ch, halves[hI][0], halves[hI][2], t) : { c: [0, 0, 0], i: 0 }
        var hx = halves[hI][1], hw = rr0.w / 2 - 4
        if (z.i > 0.02) {
          rr(ctx, hx - 8, rr0.y - 8, hw + 16, rr0.h + 16, (rr0.h + 16) / 2)
          ctx.fillStyle = root.rgba(z.c, 0.16 * z.i)
          ctx.fill()
        }
        rr(ctx, hx, rr0.y, hw, rr0.h, rr0.h / 2)
        ctx.fillStyle = root.css(root.cap)
        ctx.fill()
        ctx.fillStyle = root.rgba(z.c, 0.95 * z.i)
        ctx.fill()
      }

      // Keys.
      var r = 9
      ctx.font = "600 " + 15 + "px sans-serif"
      ctx.textAlign = "center"
      ctx.textBaseline = "middle"
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i]
        var x = k.x, y = root.keysY + root.rowY(k.row), w = k.w, h = root.rowH(k.row)
        var lc = lcs[i]
        if (lc.i > 0.03) {
          rr(ctx, x - 5, y - 5, w + 10, h + 10, r + 4)
          ctx.fillStyle = root.rgba(lc.c, 0.2 * lc.i)
          ctx.fill()
        }
        rr(ctx, x, y, w, h, r)
        ctx.fillStyle = root.css(root.cap)
        ctx.fill()
        if (lc.i > 0.01) {
          ctx.fillStyle = root.rgba(lc.c, 0.12 + 0.83 * lc.i)
          ctx.fill()
        } else {
          ctx.lineWidth = 1.2 / root.s
          ctx.strokeStyle = root.css(root.capRim)
          ctx.stroke()
        }
        if (root.showLegends && k.label) {
          var lum = (0.2126 * lc.c[0] + 0.7152 * lc.c[1] + 0.0722 * lc.c[2]) / 255 * lc.i
          ctx.fillStyle = lum > 0.42 ? "rgba(0,0,0,0.6)" : (lc.i > 0.3 ? "rgba(255,255,255,0.75)" : root.css(root.legend))
          ctx.fillText(k.label, x + w / 2, y + h / 2 + 1)
        }
        if (k.led === root.hoverLed) {
          rr(ctx, x - 3, y - 3, w + 6, h + 6, r + 2)
          ctx.lineWidth = 2 / root.s
          ctx.strokeStyle = root.css(Color.foreground, 0.9)
          ctx.stroke()
        }
      }

      // Touchpad: its lit rim.
      var tp = root.tpRect
      var tz = root.showTouchpad ? Fx.zoneColor(ch, "touchpad", 0.5, t) : { c: [0, 0, 0], i: 0 }
      if (tz.i > 0.02) {
        rr(ctx, tp.x - 8, tp.y - 8, tp.w + 16, tp.h + 16, 22)
        ctx.fillStyle = root.rgba(tz.c, 0.14 * tz.i)
        ctx.fill()
      }
      rr(ctx, tp.x, tp.y, tp.w, tp.h, 16)
      ctx.fillStyle = root.css(root.cap)
      ctx.fill()
      ctx.lineWidth = tz.i > 0.02 ? 3 : 1.2 / root.s
      ctx.strokeStyle = tz.i > 0.02 ? root.rgba(tz.c, 0.15 + 0.7 * tz.i) : root.css(root.capRim)
      ctx.stroke()

      // Lid logo (it sits on the lid; drawn here so every light is in one picture).
      var hr = root.headRect
      var hz = root.showHead ? Fx.zoneColor(ch, "head", 0.1, t) : { c: [0, 0, 0], i: 0 }
      if (hz.i > 0.02) {
        rr(ctx, hr.x - 10, hr.y - 10, hr.w + 20, hr.h + 20, (hr.h + 20) / 2)
        ctx.fillStyle = root.rgba(hz.c, 0.16 * hz.i)
        ctx.fill()
      }
      rr(ctx, hr.x, hr.y, hr.w, hr.h, hr.h / 2)
      ctx.fillStyle = root.css(root.cap)
      ctx.fill()
      if (hz.i > 0.02) {
        ctx.fillStyle = root.rgba(hz.c, 0.15 + 0.8 * hz.i)
        ctx.fill()
      } else {
        ctx.lineWidth = 1.2 / root.s
        ctx.strokeStyle = root.css(root.capRim)
        ctx.stroke()
      }
      if (!root.compact) {
        ctx.font = "500 15px sans-serif"
        ctx.fillStyle = root.css(root.legend)
        if (root.showHead) ctx.fillText("Lid logo", hr.x + hr.w / 2, hr.y + hr.h + 22)
        if (root.showTouchpad) ctx.fillText("Touchpad", tp.x + tp.w / 2, tp.y + tp.h + 22)
        if (root.showRear) ctx.fillText("Rear lights", root.rearRect.x + root.rearRect.w / 2, root.rearRect.y - 18)
      }

      // Power button: its saved colour for the current state (from the controller's flash).
      var pr = root.powerRect
      var pc = root.powerColor ? Fx.parseHex(root.powerColor) : null
      glyph(ctx, "power", pr.x, pr.y, pr.w, pc ? root.rgba(pc, 0.9) : root.css(root.capRim, 2))

      // Hovered chassis zone (paint mode).
      var hz2 = root.hoverZone === "rear" ? root.rearRect : root.hoverZone === "head" ? root.headRect : root.hoverZone === "touchpad" ? root.tpRect : null
      if (hz2) {
        rr(ctx, hz2.x - 10, hz2.y - 10, hz2.w + 20, hz2.h + 20, Math.min(22, (hz2.h + 20) / 2))
        ctx.lineWidth = 2 / root.s
        ctx.strokeStyle = root.css(Color.foreground, 0.9)
        ctx.stroke()
      }

      ctx.restore()
    }
  }

  // ---- painting
  function keyAt(px, py) {
    var ux = (px - ox) / s, uy = (py - oy) / s - keysY
    var keys = Layout.keys
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i], y = rowY(k.row)
      if (ux >= k.x - 5 && ux <= k.x + k.w + 5 && uy >= y - 5 && uy <= y + rowH(k.row) + 5) return k
    }
    return null
  }

  function zoneAt(px, py) {
    var ux = (px - ox) / s, uy = (py - oy) / s
    function inside(rc, m) { return ux >= rc.x - m && ux <= rc.x + rc.w + m && uy >= rc.y - m && uy <= rc.y + rc.h + m }
    if (showRear && inside(rearRect, 14)) return "rear"
    if (showHead && inside(headRect, 8)) return "head"
    if (showTouchpad && inside(tpRect, 8)) return "touchpad"
    return ""
  }

  property var _stroke: ({})
  function paintAt(px, py) {
    var k = keyAt(px, py)
    if (!k || _stroke[k.led] || unlit.indexOf(k.led) >= 0) return
    var st = Object.assign({}, _stroke)
    var map = {}
    map[k.led] = brush
    st[k.led] = true
    for (var j = 0; j < k.also.length; j++) map[k.also[j]] = brush
    _stroke = st
    var ov = Object.assign({}, overrides)
    for (var led in map) ov[led] = map[led]
    overrides = ov
    keysPainted(map)
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: root.paintable
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: root.paintable ? (root.keyAt(mouseX, mouseY) || root.zoneAt(mouseX, mouseY) ? Qt.CrossCursor : Qt.ArrowCursor) : Qt.PointingHandCursor
    onPressed: function(m) {
      if (!root.paintable) return
      if (m.button === Qt.RightButton) {
        var k = root.keyAt(m.x, m.y)
        if (k) {
          var lc = Fx.keyColor(root.keyboard, k.led, 0.5, 0.5, 0, root.overrides)
          root.colorPicked(Fx.toHex(lc.c))
        }
        return
      }
      root._stroke = {}
      var z = root.zoneAt(m.x, m.y)
      if (z) { root.zoneClicked(z); return }
      root.paintAt(m.x, m.y)
    }
    onPositionChanged: function(m) {
      if (!root.paintable) return
      var k = root.keyAt(m.x, m.y)
      root.hoverLed = k ? k.led : -1
      root.hoverZone = k ? "" : root.zoneAt(m.x, m.y)
      if (m.buttons & Qt.LeftButton) root.paintAt(m.x, m.y)
    }
    onExited: { root.hoverLed = -1; root.hoverZone = "" }
    onClicked: if (!root.paintable) root.clicked()
  }
}

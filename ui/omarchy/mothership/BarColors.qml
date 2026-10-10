import QtQuick
import "Effects.js" as Fx

// The colour(s) that stand for the keyboard right now: its colour, a rainbow for the colour
// cycling effects, embers for fire. `legible` keeps it readable on the bar's background.
QtObject {
  id: bc
  required property var ship
  property bool lightBackground: false
  property color fallback: "white"

  function legible(rgb) {
    // Keep the hue, move the lightness into a band that reads on the bar.
    var c = Qt.rgba(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1)
    var l = c.hslLightness
    if (lightBackground && l > 0.42) return Qt.hsla(c.hslHue < 0 ? 0 : c.hslHue, c.hslSaturation, 0.42, 1)
    if (!lightBackground && l < 0.55) return Qt.hsla(c.hslHue < 0 ? 0 : c.hslHue, c.hslSaturation, 0.6, 1)
    return c
  }

  readonly property var kb: ship.kb
  readonly property var colors: {
    var e = kb.effect
    if (e === "spectrum" || e === "wave") return [legible([255, 40, 40]), legible([40, 255, 120]), legible([60, 120, 255])]
    if (e === "aurora") return [legible([40, 255, 140]), legible([40, 200, 255]), legible([140, 60, 255])]
    if (e === "fire") return [legible([255, 200, 40]), legible([255, 90, 0]), legible([200, 20, 0])]
    if (e === "gradient" && kb.colors && kb.colors.length > 1) return [legible(Fx.parseHex(kb.colors[0])), legible(Fx.parseHex(kb.colors[1]))]
    return []
  }
  readonly property color color: {
    var e = kb.effect
    if (!ship.loaded || e === "off" || !ship.hasKeyboard) return fallback
    if (e === "static-blue") return legible([0, 255, 255])
    if (e === "perkey") {
      var keys = kb.keys || {}, first = Object.keys(keys)[0]
      return legible(Fx.parseHex(first !== undefined ? keys[first] : (kb.colors || [])[0], [255, 255, 255]))
    }
    return legible(Fx.parseHex((kb.colors || [])[0], [255, 32, 0]))
  }
}

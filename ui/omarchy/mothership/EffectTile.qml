import QtQuick
import qs.Commons
import "../../gage-ui" as G
import "Effects.js" as Fx

// A small live preview of one lighting effect (a strip of tiny keys playing it), with its name
// under it. `t` comes from the parent so every tile shares one clock.
Item {
  id: tile
  property string effect: "static"
  property string label: ""
  property bool chassis: false        // preview as a chassis light strip instead of keys
  property var colors: ["ff2000"]
  property var keys: ({})             // painted keys, for the Painted tile
  property real t: 0
  property bool selected: false
  property string fontFamily: Style.font.family
  signal clicked()

  property G.Theme theme: G.Theme {}

  implicitWidth: 96
  implicitHeight: 64

  readonly property int cols: 9
  readonly property int rows: chassis ? 1 : 3

  onTChanged: if (Fx.animated({ effect: effect }) || Fx.chassisAnimated({ effect: effect }) && chassis) canvas.requestPaint()
  onColorsChanged: canvas.requestPaint()
  onKeysChanged: canvas.requestPaint()
  onWidthChanged: canvas.requestPaint()

  Rectangle {
    id: frame
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    height: parent.height - name.height - 4
    radius: 10
    color: tile.theme.light ? Qt.tint(Color.foreground, Util.alpha(Color.background, 0.06)) : Util.alpha(Color.foreground, 0.04)
    border.width: tile.selected ? 2 : 1
    border.color: tile.selected ? Color.accent : (mouse.containsMouse ? tile.theme.ink(0.28) : tile.theme.ink(0.08))
    Behavior on border.color { ColorAnimation { duration: 140 } }

    Canvas {
      id: canvas
      anchors.fill: parent
      anchors.margins: 7
      renderStrategy: Canvas.Cooperative
      onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var gap = 2.5
        var cw = (width - gap * (tile.cols - 1)) / tile.cols
        var ch = tile.chassis ? Math.min(height, 7) : (height - gap * (tile.rows - 1)) / tile.rows
        var y0 = tile.chassis ? (height - ch) / 2 : 0
        var kb = { effect: tile.effect, colors: tile.colors, speed: 1, direction: "right", brightness: 100, on: "static", keys: tile.keys }
        var painted = tile.effect === "perkey" ? Object.keys(tile.keys || {}).map(function(k) { return tile.keys[k] }) : []
        var chs = { effect: tile.effect, colors: tile.colors, duration_ms: 3000, brightness: 100 }
        for (var r = 0; r < tile.rows; r++) {
          for (var c = 0; c < tile.cols; c++) {
            var nx = (c + 0.5) / tile.cols, ny = tile.rows > 1 ? r / (tile.rows - 1) : 0.5
            var lc
            if (tile.chassis) lc = Fx.zoneColor(chs, "all", nx, tile.t)
            else if (tile.effect === "perkey")   // a sample of the painted colours, or a hint of a brush stroke
              lc = painted.length ? { c: Fx.parseHex(painted[(r * tile.cols + c) % painted.length]), i: 1 }
                                  : { c: Fx.parseHex(tile.colors[0]), i: (r === 1 && c > 1 && c < 7) ? 1 : 0 }
            else lc = Fx.keyColor(kb, r * 31 + c, nx, 0.3 + ny * 0.7, tile.t, null)
            var x = c * (cw + gap), y = y0 + r * (ch + gap)
            ctx.beginPath()
            ctx.roundedRect(x, y, cw, ch, 2, 2)
            ctx.fillStyle = tile.theme.light ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.05)"
            ctx.fill()
            if (lc.i > 0.02) {
              ctx.fillStyle = "rgba(" + Math.round(lc.c[0]) + "," + Math.round(lc.c[1]) + "," + Math.round(lc.c[2]) + "," + (0.15 + 0.85 * lc.i) + ")"
              ctx.fill()
            }
          }
        }
      }
    }
  }

  Text {
    id: name
    anchors.bottom: parent.bottom
    anchors.horizontalCenter: parent.horizontalCenter
    text: tile.label
    color: tile.selected ? Color.foreground : tile.theme.dim(Color.foreground, 1.3)
    font.family: tile.fontFamily
    font.pixelSize: Style.font.caption
    font.weight: tile.selected ? Font.DemiBold : Font.Medium
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: tile.clicked()
  }
}

import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.Commons
import "../../gage-ui" as G
import "KeyLayout.js" as Layout

// The full view: a centred overlay card (at most 85% of the screen) with a large mirror to
// paint keys and chassis lights on, the keyboard brightness ruler beside it, and every control
// tab on the right. Esc or a click outside the card closes it.
PanelWindow {
  id: win
  required property var ship
  property string fontFamily: Style.font.family
  property string brush: ship.kbColor()
  property string side: "keyboard"
  signal dismissed()

  property G.Theme theme: G.Theme {}

  color: "transparent"
  exclusionMode: ExclusionMode.Ignore
  anchors { top: true; bottom: true; left: true; right: true }
  WlrLayershell.namespace: "mothership"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

  function close() { dismissed() }

  function fillAll() {
    var map = {}
    for (var i = 0; i < Layout.keys.length; i++) {
      var k = Layout.keys[i]
      map[k.led] = brush
      for (var j = 0; j < k.also.length; j++) map[k.also[j]] = brush
    }
    ship.paintKeys(map)
  }

  BarColors { id: glyphColors; ship: win.ship; lightBackground: win.theme.light; fallback: Color.foreground }
  StatusLine { id: statusLine; ship: win.ship }

  // Scrim: a click outside the card closes.
  Rectangle {
    anchors.fill: parent
    color: Util.alpha(Color.background, 0.72)
    MouseArea { anchors.fill: parent; onClicked: win.close() }
  }

  Rectangle {
    id: card
    width: Math.min(1560, Math.round(win.width * 0.85))
    // Tall enough for the mirror and its tools, never more than 85% of the screen.
    height: Math.min(Math.round(win.height * 0.85), Math.max(640, 22 + 44 + 18 + mirror.implicitHeight + 18 + tools.implicitHeight + 24))
    anchors.centerIn: parent
    radius: 18
    // The theme's (often glassy) popup colour over a nearly solid base: this card sits on
    // whatever is on screen, without the compositor blur the bar popups get.
    color: Qt.tint(Util.alpha(Color.background, 0.94), Color.popups.background)
    border.width: 2
    border.color: Color.popups.border
    focus: true
    Keys.onEscapePressed: win.close()
    Component.onCompleted: forceActiveFocus()
    MouseArea { anchors.fill: parent }   // clicks on the card stay on the card

    readonly property real padX: 28
    readonly property real sideW: Math.min(420, Math.max(360, width * 0.3))

    // ---- header
    Item {
      id: header
      x: card.padX
      y: 22
      width: card.width - card.padX * 2
      height: 44
      Glyph {
        id: hg
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 34; height: 34
        name: "flying-saucer-fill"
        color: win.ship.daemonUp ? glyphColors.color : win.theme.dim(Color.foreground, 1.8)
        colors: win.ship.daemonUp ? glyphColors.colors : []
      }
      Column {
        anchors.left: hg.right
        anchors.leftMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        Text {
          text: "Mothership"
          color: Color.foreground
          font.family: win.fontFamily
          font.pixelSize: Style.font.heading + 4
          font.weight: Font.DemiBold
        }
        Text {
          text: statusLine.text
          visible: text !== ""
          color: win.theme.dim(Color.foreground, 1.55)
          font.family: win.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
      Chip {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: "Close"
        fontFamily: win.fontFamily
        onClicked: win.close()
      }
    }

    // ---- left: the mirror, its brightness ruler, the brush
    Item {
      id: left
      x: card.padX
      anchors.top: header.bottom
      anchors.topMargin: 18
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 24
      width: card.width - card.padX * 2 - card.sideW - 28

      Item {
        id: hero
        width: parent.width
        height: Math.min(mirror.implicitHeight, parent.height - tools.height - 18)
        Mirror {
          id: mirror
          anchors.left: parent.left
          anchors.right: rulerCol.left
          anchors.rightMargin: 12
          height: parent.height
          compact: false
          paintable: true
          live: true
          brush: win.brush
          keyboard: win.ship.kb
          chassis: win.ship.ch
          chassisKnown: win.ship.chassisOk
          showTouchpad: win.ship.hasTouchpad
          showHead: win.ship.hasHead
          showRear: win.ship.hasRear
          unlit: win.ship.unlit
          powerColor: win.ship.powerSaved[win.ship.thermal.ac === false ? "dc-on" : "ac-full"] || ""
          onKeysPainted: function(map) { win.ship.paintKeys(map) }
          onZoneClicked: function(zone) { win.ship.chassisZone(zone, win.brush) }
          onColorPicked: function(hex) { win.brush = hex }
        }
        Column {
          id: rulerCol
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          width: 40
          spacing: 8
          TickRuler {
            id: kbRuler
            anchors.horizontalCenter: parent.horizontalCenter
            vertical: true
            width: 26
            height: Math.max(120, hero.height * 0.62)
            value: win.ship.kb.brightness === undefined ? 100 : win.ship.kb.brightness
            onReleased: function(v) { win.ship.setBrightness(v) }
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round(kbRuler.liveValue) + "%"
            color: Color.foreground
            font.family: win.fontFamily
            font.pixelSize: Style.font.caption
            font.features: { "tnum": 1 }
          }
          Glyph {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 14; height: 14
            name: "sun"
            color: win.theme.dim(Color.foreground, 1.55)
          }
        }
      }

      Column {
        id: tools
        anchors.top: hero.bottom
        anchors.topMargin: 18
        width: parent.width
        spacing: 14
        Text {
          width: parent.width
          text: {
            var z = []
            if (win.ship.hasHead) z.push("the lid logo")
            if (win.ship.hasRear) z.push("the rear lights")
            if (win.ship.hasTouchpad) z.push("the touchpad")
            var zs = z.length > 1 ? z.slice(0, -1).join(", ") + " or " + z[z.length - 1] : (z[0] || "")
            return "Click or drag across keys to paint them." + (zs && win.ship.hasChassis ? " Click " + zs + " to colour that light." : "")
                   + " Right-click a key to pick up its colour."
          }
          color: win.theme.dim(Color.foreground, 1.55)
          font.family: win.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
        Row {
          width: parent.width
          spacing: 18
          ColorPicker {
            id: brushPicker
            width: Math.min(480, parent.width - fill.width - 18)
            fontFamily: win.fontFamily
            value: win.brush
            onPicked: function(hex) { win.brush = hex }
          }
          Chip {
            id: fill
            text: "Fill every key"
            fontFamily: win.fontFamily
            showDot: true
            dot: "#" + win.brush
            onClicked: win.fillAll()
          }
        }
        Notice {
          width: parent.width
          fontFamily: win.fontFamily
          urgent: win.ship.error !== ""
          text: win.ship.error !== "" ? win.ship.error : win.ship.problems.join(" ")
        }
      }
    }

    // ---- right: every control
    Rectangle {
      id: sidePanel
      anchors.right: parent.right
      anchors.rightMargin: card.padX
      anchors.top: header.bottom
      anchors.topMargin: 18
      anchors.bottom: parent.bottom
      anchors.bottomMargin: 24
      width: card.sideW
      radius: 14
      color: Util.alpha(Color.foreground, 0.04)
      border.width: 1
      border.color: win.theme.ink(0.07)

      G.Segmented {
        id: sideTabs
        x: 16; y: 16
        width: parent.width - 32
        fontFamily: win.fontFamily
        value: win.side
        options: [{ value: "keyboard", label: "Keyboard" }, { value: "chassis", label: "Chassis" },
                  { value: "thermal", label: "Thermal" }, { value: "power", label: "Power" }]
        onPicked: function(v) { win.side = v }
      }
      Flickable {
        anchors.fill: parent
        anchors.margins: 16
        anchors.topMargin: sideTabs.y + sideTabs.height + 16
        contentHeight: sideLoader.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        Loader {
          id: sideLoader
          width: parent.width
          sourceComponent: win.side === "chassis" ? sideChassis : win.side === "thermal" ? sideThermal
                         : win.side === "power" ? sidePower : sideKeyboard
        }
      }
    }
  }

  Component { id: sideKeyboard; KeyboardTab { ship: win.ship; fontFamily: win.fontFamily } }
  Component { id: sideChassis; ChassisTab { ship: win.ship; fontFamily: win.fontFamily } }
  Component { id: sideThermal; ThermalTab { ship: win.ship; fontFamily: win.fontFamily } }
  Component { id: sidePower; PowerTab { ship: win.ship; fontFamily: win.fontFamily } }
}

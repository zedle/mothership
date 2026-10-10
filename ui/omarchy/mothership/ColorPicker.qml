import QtQuick
import qs.Commons
import "../../gage-ui" as G
import "Effects.js" as Fx

// Light colour picker: a row of preset circles (the chosen one carries a check), then "Custom"
// for a saturation/brightness square with a hue bar under it and a hex field. The presets are
// lighting data, not theme colours.
Column {
  id: picker
  property string value: ""                 // current colour, rrggbb
  property string fontFamily: Style.font.family
  property bool customOpen: false
  readonly property bool editing: hexInput.activeFocus
  signal picked(string hex)

  property G.Theme theme: G.Theme {}

  readonly property var presets: ["ff0000", "ff3c00", "ffa000", "ffe600", "30ff20", "00ffb0", "00c8ff", "1040ff", "7a1cff", "ff00c8", "ffffff"]
  readonly property bool isPreset: presets.indexOf(String(value).toLowerCase()) >= 0

  spacing: 12

  // HSV of the custom colour; follows `value` unless the person is dragging.
  property real _h: 0
  property real _s: 1
  property real _v: 1
  readonly property bool _dragging: svMouse.pressed || hueMouse.pressed
  readonly property string _custom: Fx.toHex(Fx.hsv(_h, _s, _v))
  function _sync() {
    var c = Fx.parseHex(value, [255, 32, 0])
    var mx = Math.max(c[0], c[1], c[2]), mn = Math.min(c[0], c[1], c[2])
    _v = mx / 255
    _s = mx === 0 ? 0 : (mx - mn) / mx
    if (mx !== mn) _h = Fx.hueOf(c)
  }
  onValueChanged: if (!_dragging) _sync()
  Component.onCompleted: _sync()

  function lum(hex) {
    var c = Fx.parseHex(hex)
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255
  }

  Row {
    id: swatches
    width: parent.width
    readonly property int n: picker.presets.length + 1
    readonly property real cell: Math.min(28, (width - 4 * (n - 1)) / n)
    spacing: (width - cell * n) / (n - 1)

    Repeater {
      model: picker.presets
      Item {
        required property string modelData
        width: swatches.cell
        height: swatches.cell
        readonly property bool current: picker.value.toLowerCase() === modelData
        Rectangle {
          anchors.fill: parent
          radius: width / 2
          color: "#" + modelData
          border.width: 1
          border.color: picker.theme.ink(0.2)
          scale: sm.containsMouse && !parent.current ? 1.1 : 1
          Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
        Glyph {
          anchors.centerIn: parent
          width: parent.width * 0.55
          height: width
          visible: parent.current
          name: "check"
          color: picker.lum(modelData) > 0.6 ? "black" : "white"
        }
        MouseArea {
          id: sm
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: picker.picked(modelData)
        }
      }
    }

    // Custom: a rainbow circle; it shows the custom colour (with a check) when that's in use.
    Item {
      width: swatches.cell
      height: swatches.cell
      Rectangle {
        anchors.fill: parent
        radius: width / 2
        rotation: 45
        gradient: Gradient {
          GradientStop { position: 0.0; color: "#ff0000" }
          GradientStop { position: 0.33; color: "#ffe600" }
          GradientStop { position: 0.66; color: "#00c8ff" }
          GradientStop { position: 1.0; color: "#ff00c8" }
        }
        border.width: 1
        border.color: picker.theme.ink(0.2)
      }
      Rectangle {
        anchors.centerIn: parent
        width: parent.width * (picker.isPreset || picker.value === "" ? 0.42 : 0.66)
        height: width
        radius: width / 2
        color: picker.isPreset || picker.value === "" ? Color.background : "#" + picker.value
        border.width: picker.customOpen ? 2 : 0
        border.color: Color.foreground
      }
      Glyph {
        anchors.centerIn: parent
        width: parent.width * 0.42
        height: width
        visible: !picker.isPreset && picker.value !== ""
        name: "check"
        color: picker.lum(picker.value) > 0.6 ? "black" : "white"
      }
      MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: picker.customOpen = !picker.customOpen
      }
    }
  }

  Column {
    width: parent.width
    spacing: 10
    visible: picker.customOpen

    // Saturation (left to right) and brightness (bottom to top) for the current hue.
    Item {
      id: sv
      width: parent.width
      height: Math.round(width * 0.36)
      Rectangle {
        id: svBase
        anchors.fill: parent
        radius: 10
        color: "#" + Fx.toHex(Fx.hsv(picker._h, 1, 1))
        border.width: 1
        border.color: picker.theme.ink(0.15)
      }
      Rectangle {
        anchors.fill: parent
        radius: 10
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0; color: "#ffffffff" }
          GradientStop { position: 1; color: "#00ffffff" }
        }
      }
      Rectangle {
        anchors.fill: parent
        radius: 10
        gradient: Gradient {
          GradientStop { position: 0; color: "#00000000" }
          GradientStop { position: 1; color: "#ff000000" }
        }
      }
      Rectangle {
        x: picker._s * sv.width - width / 2
        y: (1 - picker._v) * sv.height - height / 2
        width: 18; height: 18; radius: 9
        color: "#" + picker._custom
        border.width: 2
        border.color: "white"
        Rectangle {
          anchors.fill: parent
          anchors.margins: -1
          radius: width / 2
          color: "transparent"
          border.width: 1
          border.color: "#66000000"
        }
      }
      MouseArea {
        id: svMouse
        anchors.fill: parent
        cursorShape: Qt.CrossCursor
        function set(m) {
          picker._s = Math.max(0, Math.min(1, m.x / width))
          picker._v = Math.max(0, Math.min(1, 1 - m.y / height))
        }
        onPressed: function(m) { set(m) }
        onPositionChanged: function(m) { if (pressed) set(m) }
        onReleased: picker.picked(picker._custom)
      }
    }

    // Hue
    Item {
      width: parent.width
      height: 14
      Rectangle {
        anchors.fill: parent
        radius: 7
        border.width: 1
        border.color: picker.theme.ink(0.15)
        gradient: Gradient {
          orientation: Gradient.Horizontal
          GradientStop { position: 0 / 6; color: "#ff0000" }
          GradientStop { position: 1 / 6; color: "#ffff00" }
          GradientStop { position: 2 / 6; color: "#00ff00" }
          GradientStop { position: 3 / 6; color: "#00ffff" }
          GradientStop { position: 4 / 6; color: "#0000ff" }
          GradientStop { position: 5 / 6; color: "#ff00ff" }
          GradientStop { position: 6 / 6; color: "#ff0000" }
        }
      }
      Rectangle {
        x: Math.max(0, Math.min(parent.width - width, picker._h * parent.width - width / 2))
        anchors.verticalCenter: parent.verticalCenter
        width: 18; height: 18; radius: 9
        color: "#" + Fx.toHex(Fx.hsv(picker._h, 1, 1))
        border.width: 2
        border.color: "white"
      }
      MouseArea {
        id: hueMouse
        anchors.fill: parent
        anchors.margins: -4
        cursorShape: Qt.PointingHandCursor
        function set(x) { picker._h = Math.max(0, Math.min(0.999, (x - 4) / (width - 8))) }
        onPressed: function(m) { set(m.x) }
        onPositionChanged: function(m) { if (pressed) set(m.x) }
        onReleased: picker.picked(picker._custom)
      }
    }

    Row {
      spacing: 8
      Rectangle {
        width: 104; height: 26; radius: 7
        color: Util.alpha(Color.foreground, 0.06)
        border.width: 1
        border.color: hexInput.activeFocus ? Util.alpha(Color.accent, 0.85) : picker.theme.ink(0.1)
        Text {
          anchors.left: parent.left
          anchors.leftMargin: 9
          anchors.verticalCenter: parent.verticalCenter
          text: "#"
          color: picker.theme.dim(Color.foreground, 1.55)
          font.family: picker.fontFamily
          font.pixelSize: Style.font.bodySmall
        }
        TextInput {
          id: hexInput
          anchors.fill: parent
          anchors.leftMargin: 20
          anchors.rightMargin: 8
          verticalAlignment: TextInput.AlignVCenter
          text: picker._dragging ? picker._custom : picker.value
          color: Color.foreground
          selectionColor: Util.alpha(Color.accent, 0.4)
          font.family: picker.fontFamily
          font.pixelSize: Style.font.bodySmall
          font.features: { "tnum": 1 }
          maximumLength: 6
          validator: RegularExpressionValidator { regularExpression: /[0-9a-fA-F]{0,6}/ }
          onAccepted: {
            if (/^[0-9a-fA-F]{6}$/.test(text)) picker.picked(text.toLowerCase())
            focus = false
          }
          Keys.onEscapePressed: { text = picker.value; focus = false }
        }
      }
      Text {
        anchors.verticalCenter: parent.verticalCenter
        text: hexInput.activeFocus ? "Enter to apply" : "Drag in the square, or type a hex colour"
        color: picker.theme.dim(Color.foreground, 1.55)
        font.family: picker.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}

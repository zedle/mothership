import QtQuick
import qs.Commons
import qs.Ui
import "../../gage-ui" as G
import "Effects.js" as Fx

// Chassis lights (lid logo, rear lights, touchpad): effect tiles first, then one colour for all
// or, with "Separate zones", one row per light.
Column {
  id: tab
  required property var ship
  property string fontFamily: Style.font.family
  property string zone: "head"
  property bool separate: false
  readonly property bool editing: picker.editing

  property G.Theme theme: G.Theme {}
  spacing: 12

  readonly property var ch: ship.ch
  readonly property string eff: ch.effect || "static"

  property real t: 0
  readonly property real t0: Date.now()
  Timer {
    interval: 66
    repeat: true
    running: tab.visible
    onTriggered: tab.t = (Date.now() - tab.t0) / 1000
  }

  onZoneRowsChanged: if (zoneRows.length && !zoneRows.some(function(z) { return z.id === tab.zone })) zone = zoneRows[0].id
  Component.onCompleted: {
    var z = ch.zones || {}
    separate = !!(z.head && z.rear && z.touchpad && !(z.head === z.rear && z.rear === z.touchpad))
  }

  readonly property var zoneRows: [{ id: "head", label: "Lid logo" }, { id: "rear", label: "Rear lights" }, { id: "touchpad", label: "Touchpad" }]
                                   .filter(function(z) { return tab.ship.hasZone(z.id) })
  readonly property string zoneList: {
    var names = zoneRows.map(function(z) { return z.label.charAt(0).toLowerCase() + z.label.slice(1) })
    return names.length > 1 ? names.slice(0, -1).join(", ") + " and " + names[names.length - 1] : (names[0] || "")
  }
  function zoneHex(z) { return Fx.toHex(Fx.zoneColor(ch, z, 0.5, 0).c) }
  readonly property string effectColor: (ch.colors && ch.colors[0]) || "00f0f0"

  Text {
    width: parent.width
    visible: tab.ship.loaded && !tab.ship.hasChassis
    text: "No supported lighting controller found on this machine."
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }

  Grid {
    id: grid
    width: parent.width
    columns: 4
    spacing: 8
    readonly property real cellW: (width - spacing * (columns - 1)) / columns
    visible: tab.ship.hasChassis || !tab.ship.loaded
    Repeater {
      model: [{ id: "static", label: "Static" }, { id: "breathing", label: "Breathing" },
              { id: "pulse", label: "Pulse" }, { id: "morph", label: "Morph" },
              { id: "spectrum", label: "Spectrum" }, { id: "wave", label: "Wave" }, { id: "off", label: "Off" }]
      EffectTile {
        required property var modelData
        width: grid.cellW
        height: 46
        chassis: true
        effect: modelData.id
        label: modelData.label
        t: tab.t
        colors: [modelData.id === "static" ? tab.zoneHex("head") : tab.effectColor]
        fontFamily: tab.fontFamily
        selected: tab.eff === modelData.id
        onClicked: {
          var takesColour = ["breathing", "pulse", "morph"].indexOf(modelData.id) >= 0
          tab.ship.chassisEffect(modelData.id, takesColour ? tab.effectColor : "")
        }
      }
    }
  }

  Item {
    width: parent.width
    height: Math.max(sepSwitch.implicitHeight, sepText.implicitHeight)
    visible: tab.ship.hasChassis && tab.eff === "static" && tab.zoneRows.length > 1
    Column {
      id: sepText
      anchors.left: parent.left
      anchors.right: sepSwitch.left
      anchors.verticalCenter: parent.verticalCenter
      Text {
        text: "Separate zones"
        color: Color.foreground
        font.family: tab.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        text: tab.separate ? "Pick a light, then its colour." : "One colour for the " + tab.zoneList + "."
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    ToggleSwitch {
      id: sepSwitch
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      cursorRing: false
      checked: tab.separate
      onToggled: tab.separate = !tab.separate
    }
  }

  Column {
    width: parent.width
    spacing: 6
    visible: tab.ship.hasChassis && tab.eff === "static" && tab.separate
    Repeater {
      model: tab.zoneRows
      G.Card {
        id: row
        required property var modelData
        readonly property bool current: tab.zone === modelData.id
        width: parent.width
        height: 40
        radius: 11
        hot: zm.containsMouse
        border.color: current ? Util.alpha(Color.accent, 0.85) : tab.theme.ink(0.07)
        Rectangle {
          id: dot
          anchors.left: parent.left
          anchors.leftMargin: 14
          anchors.verticalCenter: parent.verticalCenter
          width: 8; height: 8; radius: 4
          color: row.current ? Color.accent : tab.theme.ink(0.25)
        }
        Text {
          anchors.left: dot.right
          anchors.leftMargin: 10
          anchors.verticalCenter: parent.verticalCenter
          text: row.modelData.label
          color: Color.foreground
          font.family: tab.fontFamily
          font.pixelSize: Style.font.body
          font.weight: row.current ? Font.DemiBold : Font.Normal
        }
        Rectangle {
          anchors.right: parent.right
          anchors.rightMargin: 12
          anchors.verticalCenter: parent.verticalCenter
          width: 22; height: 22; radius: 11
          color: "#" + tab.zoneHex(row.modelData.id)
          border.width: 1
          border.color: tab.theme.ink(0.2)
        }
        MouseArea {
          id: zm
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: tab.zone = row.modelData.id
        }
      }
    }
  }

  ColorPicker {
    id: picker
    width: parent.width
    visible: tab.ship.hasChassis && ["spectrum", "wave", "off"].indexOf(tab.eff) < 0
    fontFamily: tab.fontFamily
    value: tab.eff !== "static" ? tab.effectColor : tab.zoneHex(tab.separate ? tab.zone : "head")
    onPicked: function(hex) {
      if (tab.eff === "static") tab.ship.chassisZone(tab.separate ? tab.zone : "all", hex)
      else tab.ship.chassisEffect(tab.eff, hex)
    }
  }

  Column {
    width: parent.width
    spacing: 6
    visible: tab.ship.hasChassis
    Heading {
      width: parent.width
      text: "Brightness"
      value: Math.round(ruler.liveValue) + "%"
      fontFamily: tab.fontFamily
    }
    TickRuler {
      id: ruler
      width: parent.width
      value: tab.ch.brightness === undefined ? 100 : tab.ch.brightness
      onReleased: function(v) { tab.ship.chassisBrightness(v) }
    }
  }
}

import QtQuick
import qs.Commons
import "../../gage-ui" as G

// A pill choice: effect names, zones, states. `dot` shows a colour (a light's colour, data);
// `dots` (two or more) shows a gradient dot.
Rectangle {
  id: chip
  property string text: ""
  property bool selected: false
  property bool enabled: true
  property color dot: "transparent"
  property var dots: []
  property bool showDot: false
  property string fontFamily: Style.font.family
  signal clicked()

  property G.Theme theme: G.Theme {}

  implicitHeight: 30
  implicitWidth: row.implicitWidth + 20
  radius: 9
  opacity: enabled ? 1 : 0.4
  color: selected ? Util.alpha(Color.accent, theme.light ? 0.16 : 0.2)
                  : Util.alpha(Color.foreground, mouse.containsMouse ? 0.12 : 0.06)
  border.width: 1
  border.color: selected ? Util.alpha(Color.accent, 0.85) : theme.ink(0.07)
  Behavior on color { ColorAnimation { duration: 140 } }
  Behavior on border.color { ColorAnimation { duration: 140 } }

  Row {
    id: row
    anchors.centerIn: parent
    spacing: 6
    Rectangle {
      visible: chip.showDot
      anchors.verticalCenter: parent.verticalCenter
      width: 9; height: 9; radius: 4.5
      color: chip.dots.length > 1 ? "transparent" : chip.dot
      border.width: 1
      border.color: chip.theme.ink(0.18)
      gradient: chip.dots.length > 1 ? dotGradient : null
      Gradient {
        id: dotGradient
        orientation: Gradient.Horizontal
        GradientStop { position: 0; color: chip.dots.length > 0 ? chip.dots[0] : "transparent" }
        GradientStop { position: 0.5; color: chip.dots.length > 2 ? chip.dots[1] : (chip.dots.length > 0 ? chip.dots[0] : "transparent") }
        GradientStop { position: 1; color: chip.dots.length > 0 ? chip.dots[chip.dots.length - 1] : "transparent" }
      }
    }
    Text {
      anchors.verticalCenter: parent.verticalCenter
      text: chip.text
      color: chip.selected ? Color.foreground : chip.theme.dim(Color.foreground, 1.3)
      font.family: chip.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.weight: chip.selected ? Font.DemiBold : Font.Medium
    }
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    enabled: chip.enabled
    cursorShape: Qt.PointingHandCursor
    onClicked: chip.clicked()
  }
}

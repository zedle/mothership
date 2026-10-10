import QtQuick
import qs.Commons
import "../../gage-ui" as G

// A ruler of thin ticks: the ticks up to the value are bright, the rest faint. Drag or click
// to set (snapping to `step`); the wheel steps. Vertical rulers fill from the bottom.
Item {
  id: ruler
  property real value: 100
  property real minimum: 0
  property real maximum: 100
  property real step: 5
  readonly property real span: Math.max(0.0001, maximum - minimum)
  property bool vertical: false
  property int ticks: vertical ? 26 : 40
  property int majorEvery: 5          // every nth tick is long
  property color tint: Color.foreground
  property real liveValue: value
  property bool dragging: false
  signal released(real value)

  property G.Theme theme: G.Theme {}

  onValueChanged: if (!dragging) liveValue = value
  implicitWidth: vertical ? 30 : 240
  implicitHeight: vertical ? 160 : 26

  Repeater {
    model: ruler.ticks
    Rectangle {
      required property int index
      readonly property real frac: index / (ruler.ticks - 1)
      readonly property bool on: frac <= (ruler.liveValue - ruler.minimum) / ruler.span + 0.001 && ruler.liveValue > ruler.minimum
      readonly property bool major: index % ruler.majorEvery === 0
      // Horizontal: ticks stand left to right. Vertical: they lie bottom to top.
      width: ruler.vertical ? (major ? ruler.width : ruler.width * 0.62) : 2
      height: ruler.vertical ? 2 : (major ? ruler.height : ruler.height * 0.62)
      radius: 1
      x: ruler.vertical ? (ruler.width - width) / 2 : frac * (ruler.width - 2)
      y: ruler.vertical ? (1 - frac) * (ruler.height - 2) : (ruler.height - height) / 2
      color: on ? ruler.tint : ruler.theme.ink(ruler.theme.light ? 0.18 : 0.14)
      Behavior on color { ColorAnimation { duration: 90 } }
    }
  }

  MouseArea {
    anchors.fill: parent
    anchors.margins: -6
    cursorShape: Qt.PointingHandCursor
    function at(m) {
      var f = ruler.vertical ? 1 - (m.y - 6) / ruler.height : (m.x - 6) / ruler.width
      var v = ruler.minimum + Math.round(Math.max(0, Math.min(1, f)) * ruler.span / ruler.step) * ruler.step
      return Math.max(ruler.minimum, Math.min(ruler.maximum, v))
    }
    onPressed: function(m) { ruler.dragging = true; ruler.liveValue = at(m) }
    onPositionChanged: function(m) { if (pressed) ruler.liveValue = at(m) }
    onReleased: { ruler.dragging = false; ruler.released(ruler.liveValue) }
    onWheel: function(w) {
      var v = Math.max(ruler.minimum, Math.min(ruler.maximum, ruler.liveValue + (w.angleDelta.y > 0 ? ruler.step : -ruler.step)))
      ruler.liveValue = v
      ruler.released(v)
    }
  }
}

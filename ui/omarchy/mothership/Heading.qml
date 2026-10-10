import QtQuick
import qs.Commons
import "../../gage-ui" as G

// A section title in sentence case, with an optional value on the right.
Item {
  id: h
  property string text: ""
  property string value: ""
  property string fontFamily: Style.font.family
  property G.Theme theme: G.Theme {}
  implicitHeight: label.implicitHeight + 2
  implicitWidth: 200

  Text {
    id: label
    anchors.left: parent.left
    anchors.bottom: parent.bottom
    text: h.text
    color: h.theme.dim(Color.foreground, 1.45)
    font.family: h.fontFamily
    font.pixelSize: Style.font.bodySmall
    font.weight: Font.DemiBold
  }
  Text {
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    visible: h.value !== ""
    text: h.value
    color: Color.foreground
    font.family: h.fontFamily
    font.pixelSize: Style.font.bodySmall
    font.features: { "tnum": 1 }
  }
}

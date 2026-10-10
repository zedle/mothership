import QtQuick
import qs.Commons
import "../../gage-ui" as G

// A quiet one-line notice with an info glyph: the daemon's problems or a connection error.
// `urgent` (the daemon is unreachable) tints it; otherwise it stays dim.
Item {
  id: notice
  property string text: ""
  property bool urgent: false
  property string fontFamily: Style.font.family
  property G.Theme theme: G.Theme {}

  visible: text !== ""
  implicitHeight: visible ? Math.max(16, label.implicitHeight) : 0

  Glyph {
    id: icon
    anchors.left: parent.left
    anchors.top: parent.top
    anchors.topMargin: 1
    width: 14; height: 14
    name: notice.urgent ? "warning" : "info"
    color: notice.urgent ? Color.urgent : notice.theme.dim(Color.foreground, 1.55)
  }
  Text {
    id: label
    anchors.left: icon.right
    anchors.leftMargin: 7
    anchors.right: parent.right
    text: notice.text
    color: notice.urgent ? Color.urgent : notice.theme.dim(Color.foreground, 1.55)
    font.family: notice.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    maximumLineCount: 2
    elide: Text.ElideRight
  }
}

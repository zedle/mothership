import QtQuick
import QtQuick.Shapes
import "Icons.js" as Icons

// One Phosphor icon as a vector path. `colors` (two or more) fills it with a diagonal
// gradient instead of the flat `color`.
Item {
  id: root
  property string name: ""
  property color color: "white"
  property var colors: []

  implicitWidth: 16
  implicitHeight: 16

  Shape {
    id: shape
    anchors.centerIn: parent
    width: 256
    height: 256
    scale: Math.min(root.width, root.height) / 256
    visible: Icons.paths[root.name] !== undefined
    preferredRendererType: Shape.CurveRenderer
    ShapePath {
      strokeWidth: -1
      fillColor: root.colors.length > 1 ? "transparent" : root.color
      fillGradient: root.colors.length > 1 ? grad : null
      PathSvg { path: Icons.paths[root.name] || "" }
    }
  }

  LinearGradient {
    id: grad
    x1: 24; y1: 24; x2: 232; y2: 232
    GradientStop { position: 0; color: root.colors.length > 0 ? root.colors[0] : root.color }
    GradientStop { position: 0.5; color: root.colors.length > 2 ? root.colors[1] : (root.colors.length > 0 ? root.colors[0] : root.color) }
    GradientStop { position: 1; color: root.colors.length > 0 ? root.colors[root.colors.length - 1] : root.color }
  }
}

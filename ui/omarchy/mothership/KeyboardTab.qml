import QtQuick
import qs.Commons
import qs.Ui
import "../../gage-ui" as G

// Keyboard lighting: effects as live preview tiles, colour, speed, light-as-I-type. The
// brightness ruler sits next to the mirror.
Column {
  id: tab
  required property var ship
  property string fontFamily: Style.font.family
  readonly property bool editing: kbPicker.editing

  property G.Theme theme: G.Theme {}
  spacing: 12

  readonly property var kb: ship.kb
  readonly property string eff: kb.effect || "static"
  readonly property bool painted: Object.keys(kb.keys || {}).length > 0

  // One clock for every tile.
  property real t: 0
  readonly property real t0: Date.now()
  Timer {
    interval: 66
    repeat: true
    running: tab.visible
    onTriggered: tab.t = (Date.now() - tab.t0) / 1000
  }

  readonly property var effects: [
    { id: "static", label: "Static" }, { id: "breathing", label: "Breathing" },
    { id: "wave", label: "Wave" }, { id: "spectrum", label: "Spectrum" },
    { id: "scanner", label: "Scanner" }, { id: "aurora", label: "Aurora" },
    { id: "gradient", label: "Gradient" }, { id: "fire", label: "Fire" },
    { id: "perkey", label: "Painted" }, { id: "off", label: "Off" }
  ]
  readonly property var notes: ({
    "static": "One colour across the keyboard.",
    "static-blue": "The firmware's own cyan.",
    "breathing": "Fades in and out.",
    "wave": "A rainbow rolls across the keys.",
    "spectrum": "The whole keyboard cycles through every colour.",
    "scanner": "A band of light sweeps side to side.",
    "aurora": "Slow greens and blues drifting.",
    "gradient": "A blend from one colour to the next.",
    "fire": "Flames rise from the space bar and the keys you press flare. Picking a colour switches to Static.",
    "perkey": tab.painted ? "Your painted keys. Open the full window to paint more." : "Open the full window and paint keys one by one.",
    "off": "The keyboard is dark."
  })
  readonly property bool hasSpeed: ["breathing", "wave", "spectrum", "scanner", "aurora"].indexOf(eff) >= 0
  readonly property bool canReact: ["fire", "off", "perkey"].indexOf(eff) < 0

  Text {
    width: parent.width
    visible: tab.ship.loaded && !tab.ship.hasKeyboard
    text: "No supported per-key keyboard found on this machine."
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }

  Grid {
    id: grid
    width: parent.width
    columns: 5
    spacing: 8
    readonly property real cellW: (width - spacing * (columns - 1)) / columns
    visible: tab.ship.hasKeyboard || !tab.ship.loaded
    Repeater {
      model: tab.effects
      EffectTile {
        required property var modelData
        width: grid.cellW
        height: 58
        effect: modelData.id
        label: modelData.label
        t: tab.t
        colors: ["static", "breathing", "scanner", "gradient"].indexOf(modelData.id) >= 0 ? tab.ship.kbColors() : ["ff2000"]
        keys: tab.kb.keys || ({})
        fontFamily: tab.fontFamily
        selected: tab.eff === modelData.id || (modelData.id === "static" && tab.eff === "static-blue")
        onClicked: tab.ship.setEffect(modelData.id)
      }
    }
  }

  Text {
    width: parent.width
    visible: tab.ship.hasKeyboard
    text: tab.notes[tab.eff] || ""
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  ColorPicker {
    id: kbPicker
    width: parent.width
    visible: tab.ship.hasKeyboard
    fontFamily: tab.fontFamily
    value: ["spectrum", "wave", "aurora", "fire", "off", "perkey"].indexOf(tab.eff) >= 0 ? "" : tab.ship.kbColor()
    onPicked: function(hex) { tab.ship.setColor(hex) }
  }

  Row {
    width: parent.width
    spacing: 8
    visible: tab.ship.hasKeyboard && tab.hasSpeed
    G.Segmented {
      width: tab.eff === "wave" ? (parent.width - 8) * 0.5 : parent.width
      fontFamily: tab.fontFamily
      value: tab.kb.speed === undefined ? 1 : tab.kb.speed
      options: [{ value: 0, label: "Slow" }, { value: 1, label: "Medium" }, { value: 2, label: "Fast" }]
      onPicked: function(v) { tab.ship.setSpeed(v) }
    }
    G.Segmented {
      visible: tab.eff === "wave"
      width: (parent.width - 8) * 0.5
      fontFamily: tab.fontFamily
      value: tab.kb.direction || "right"
      options: [{ value: "left", label: "←" }, { value: "right", label: "→" },
                { value: "up", label: "↑" }, { value: "down", label: "↓" }]
      onPicked: function(v) { tab.ship.setDirection(v) }
    }
  }

  Item {
    width: parent.width
    height: Math.max(reactSwitch.implicitHeight, reactText.implicitHeight)
    visible: tab.ship.hasKeyboard
    opacity: tab.canReact ? 1 : 0.45
    Column {
      id: reactText
      anchors.left: parent.left
      anchors.right: reactSwitch.left
      anchors.verticalCenter: parent.verticalCenter
      Text {
        text: "Light keys as I type"
        color: Color.foreground
        font.family: tab.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        text: tab.canReact ? "The effect shows only on keys you press." : "Not with " + (tab.eff === "perkey" ? "painted keys" : tab.eff) + "."
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    ToggleSwitch {
      id: reactSwitch
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      cursorRing: false
      interactive: tab.canReact
      checked: tab.ship.reactive && tab.canReact
      onToggled: tab.ship.setReactive(!checked)
    }
  }
}

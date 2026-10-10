import QtQuick
import qs.Commons
import "../../gage-ui" as G
import "Effects.js" as Fx

// Power-button colours per power state. The controller keeps these in its flash memory, so
// picks stay a draft until "Save to controller" and a second, explicit confirmation.
Column {
  id: tab
  required property var ship
  property string fontFamily: Style.font.family
  readonly property bool editing: picker.editing

  property G.Theme theme: G.Theme {}
  spacing: 12

  // One row per state the person thinks about; "Asleep" covers both sleep states.
  readonly property var rows: [
    { id: "ac", label: "Plugged in", note: "Steady", states: ["ac-full"], icon: "plug" },
    { id: "charging", label: "Charging", note: "Breathes slowly", states: ["ac-charging"], icon: "battery-charging" },
    { id: "battery", label: "On battery", note: "Steady", states: ["dc-on"], icon: "battery-full" },
    { id: "low", label: "Low battery", note: "Pulses", states: ["dc-low"], icon: "battery-low" },
    { id: "sleep", label: "Asleep", note: "Breathes", states: ["ac-sleep", "dc-sleep"], icon: "moon" }
  ]

  property var drafts: ({})        // row id -> rrggbb
  property string editingRow: ""
  property bool confirming: false
  property bool confirmingSetup: false
  property bool saving: false
  property string result: ""

  readonly property int draftCount: Object.keys(drafts).length

  function saved(row) {
    var s = ship.powerSaved
    return s[row.states[0]] || ""
  }
  function shown(row) { return drafts[row.id] || saved(row) }

  function setDraft(row, hex) {
    var d = Object.assign({}, drafts)
    if (hex === saved(row)) delete d[row.id]
    else d[row.id] = hex
    drafts = d
    result = ""
  }

  function save() {
    var states = {}
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i]
      if (drafts[r.id]) r.states.forEach(function(st) { states[st] = tab.drafts[r.id] })
    }
    saving = true
    ship.savePower(states, function(ok) {
      tab.saving = false
      tab.confirming = false
      if (ok) { tab.drafts = {}; tab.result = "Saved. The power button uses these from now on." }
      else tab.result = ""
    })
  }

  Text {
    width: parent.width
    text: "The power button shows these by itself, even when mothership isn't running."
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  Text {
    width: parent.width
    visible: tab.ship.loaded && !tab.ship.hasChassis
    text: "No lighting controller with a power button found."
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.body
  }

  Column {
    width: parent.width
    spacing: 6
    visible: tab.ship.hasChassis
    Repeater {
      model: tab.rows
      Column {
        id: rowItem
        required property var modelData
        width: tab.width
        spacing: 8
        readonly property bool open: tab.editingRow === modelData.id
        readonly property string hex: tab.shown(modelData)
        readonly property bool changed: tab.drafts[modelData.id] !== undefined

        G.Card {
          width: parent.width
          height: 46
          radius: 12
          hot: rowMouse.containsMouse || rowItem.open
          border.color: rowItem.changed ? Util.alpha(Color.accent, 0.8) : tab.theme.ink(0.07)
          Glyph {
            id: rowIcon
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 18; height: 18
            name: rowItem.modelData.icon
            color: tab.theme.dim(Color.foreground, 1.3)
          }
          Column {
            anchors.left: rowIcon.right
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            Text {
              text: rowItem.modelData.label
              color: Color.foreground
              font.family: tab.fontFamily
              font.pixelSize: Style.font.body
            }
            Text {
              text: rowItem.changed ? "Not saved yet" : (rowItem.hex ? rowItem.modelData.note : "Not set by mothership")
              color: rowItem.changed ? Color.accent : tab.theme.dim(Color.foreground, 1.55)
              font.family: tab.fontFamily
              font.pixelSize: Style.font.caption
            }
          }
          Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 26; height: 26; radius: 13
            color: rowItem.hex ? "#" + rowItem.hex : "transparent"
            border.width: rowItem.hex ? 1 : 1.5
            border.color: rowItem.hex ? tab.theme.ink(0.2) : tab.theme.dim(Color.foreground, 2)
          }
          MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: tab.editingRow = rowItem.open ? "" : rowItem.modelData.id
          }
        }
      }
    }
  }

  ColorPicker {
    id: picker
    width: parent.width
    visible: tab.editingRow !== ""
    fontFamily: tab.fontFamily
    value: {
      for (var i = 0; i < tab.rows.length; i++) if (tab.rows[i].id === tab.editingRow) return tab.shown(tab.rows[i])
      return ""
    }
    onPicked: function(hex) {
      for (var i = 0; i < tab.rows.length; i++) if (tab.rows[i].id === tab.editingRow) tab.setDraft(tab.rows[i], hex)
    }
  }

  // ---- save, with an explicit confirmation
  G.Card {
    width: parent.width
    visible: tab.confirming
    height: confirmCol.implicitHeight + 24
    radius: 12
    border.color: Util.alpha(Color.urgent, 0.7)
    Column {
      id: confirmCol
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: 12
      spacing: 10
      Row {
        spacing: 8
        Glyph {
          width: 16; height: 16
          name: "warning"
          color: Color.urgent
        }
        Text {
          text: "Write to the lighting controller?"
          color: Color.foreground
          font.family: tab.fontFamily
          font.pixelSize: Style.font.body
          font.weight: Font.DemiBold
        }
      }
      Text {
        width: parent.width
        text: "These colours are stored in the controller's flash memory, which wears a little with every write. Save once you're happy with them, not while experimenting."
        color: tab.theme.dim(Color.foreground, 1.4)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Row {
        spacing: 8
        Chip {
          text: "Cancel"
          fontFamily: tab.fontFamily
          enabled: !tab.saving
          onClicked: tab.confirming = false
        }
        Chip {
          text: tab.saving ? "Saving…" : "Save to controller"
          fontFamily: tab.fontFamily
          selected: true
          enabled: !tab.saving
          onClicked: tab.save()
        }
      }
    }
  }

  Row {
    width: parent.width
    spacing: 8
    visible: tab.ship.hasChassis && !tab.confirming
    Chip {
      text: "Save to controller"
      fontFamily: tab.fontFamily
      enabled: tab.draftCount > 0
      selected: tab.draftCount > 0
      onClicked: tab.confirming = true
    }
    Chip {
      text: "Discard changes"
      fontFamily: tab.fontFamily
      visible: tab.draftCount > 0
      onClicked: { tab.drafts = {}; tab.editingRow = "" }
    }
  }

  Text {
    width: parent.width
    visible: tab.result !== ""
    text: tab.result
    color: tab.theme.green
    font.family: tab.fontFamily
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
  }

  // ---- system: graphics mode
  Rectangle {
    width: parent.width
    height: 1
    color: tab.theme.ink(0.08)
    visible: gfx.visible
  }

  Heading {
    width: parent.width
    text: "System"
    fontFamily: tab.fontFamily
    visible: gfx.visible
  }

  G.Card {
    id: gfx
    readonly property var g: tab.ship.graphics
    readonly property string modeText: !g ? "" : g.mode === "hybrid" ? "Hybrid (integrated GPU drives the screen)"
                                     : g.mode === "discrete" ? "Discrete GPU only" : "Unknown"
    visible: !!g
    width: parent.width
    height: 52
    radius: 12
    Glyph {
      id: gfxIcon
      anchors.left: parent.left
      anchors.leftMargin: 12
      anchors.verticalCenter: parent.verticalCenter
      width: 18; height: 18
      name: "graphics-card"
      color: tab.theme.dim(Color.foreground, 1.3)
    }
    Column {
      anchors.left: gfxIcon.right
      anchors.leftMargin: 10
      anchors.right: setupChip.left
      anchors.rightMargin: 8
      anchors.verticalCenter: parent.verticalCenter
      Text {
        text: "Graphics"
        color: Color.foreground
        font.family: tab.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        text: gfx.modeText
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        elide: Text.ElideRight
      }
    }
    Chip {
      id: setupChip
      anchors.right: parent.right
      anchors.rightMargin: 10
      anchors.verticalCenter: parent.verticalCenter
      text: "Change in setup\u2026"
      fontFamily: tab.fontFamily
      selected: tab.confirmingSetup
      onClicked: tab.confirmingSetup = !tab.confirmingSetup
    }
  }

  G.Card {
    width: parent.width
    visible: gfx.visible && tab.confirmingSetup
    height: setupCol.implicitHeight + 24
    radius: 12
    border.color: Util.alpha(Color.urgent, 0.7)
    Column {
      id: setupCol
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      anchors.margins: 12
      spacing: 10
      Row {
        spacing: 8
        Glyph {
          width: 16; height: 16
          name: "warning"
          color: Color.urgent
        }
        Text {
          text: "Restart into setup?"
          color: Color.foreground
          font.family: tab.fontFamily
          font.pixelSize: Style.font.body
          font.weight: Font.DemiBold
        }
      }
      Text {
        width: parent.width
        text: "The laptop restarts into its setup screen. Change Graphics mode there, then save and exit. Save your work first: open apps close."
        color: tab.theme.dim(Color.foreground, 1.4)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Row {
        spacing: 8
        Chip {
          text: "Cancel"
          fontFamily: tab.fontFamily
          onClicked: tab.confirmingSetup = false
        }
        Chip {
          text: "Restart into setup"
          fontFamily: tab.fontFamily
          selected: true
          onClicked: { tab.confirmingSetup = false; tab.ship.restartToSetup() }
        }
      }
    }
  }
}

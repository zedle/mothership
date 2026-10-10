import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "../../gage-ui" as G

// mothership: Alienware lighting and thermal control (a front end for mothershipd).
// The bar glyph wears the keyboard's colour and pulses in G-Mode; the popup has a live mirror
// of the machine and Lights / Thermal / Power tabs; "Full window" opens a paintable mirror.
BarWidget {
  id: root
  moduleName: "mothership"

  readonly property bool opened: controller.open
  property bool popoutSwitchClosing: false
  property bool windowOpen: false
  property string tab: "keyboard"

  function open() { controller.show() }
  function close() { controller.hide() }
  function toggle() { opened ? close() : open() }
  function closeForPopoutSwitch() {
    popoutSwitchClosing = true
    close()
    Qt.callLater(function() { root.popoutSwitchClosing = false })
  }
  function switchPanel(direction) {
    return bar && typeof bar.switchPanelFrom === "function" ? bar.switchPanelFrom(root, direction) : false
  }
  function openWindow() {
    close()
    windowOpen = true
  }

  PanelController { id: controller }

  readonly property color barForeground: bar ? bar.barForeground : Color.foreground
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  property G.Theme theme: G.Theme {}

  Ship {
    id: core
    command: {
      var c = String(root.setting("command", "") || "").trim()
      return c ? c.split(/\s+/) : []
    }
    fast: root.opened || root.windowOpen
  }
  StatusLine { id: statusLine; ship: core }
  BarColors {
    id: barColors
    ship: core
    lightBackground: root.barForeground.hslLightness < 0.5
    fallback: root.barForeground
  }
  BarColors {
    id: popupColors
    ship: core
    lightBackground: root.theme.light
    fallback: Color.foreground
  }

  readonly property bool notInstalled: core.error.indexOf("isn't installed") >= 0
  readonly property bool noHardware: core.loaded && !core.hasKeyboard && !core.hasChassis && !core.hasThermal
  readonly property bool shown: !notInstalled && !noHardware

  function snapshot() {
    return {
      daemon: core.daemonUp, error: core.error, problems: core.problems,
      keyboard: core.kb, chassis: core.ch,
      thermal: { mode: core.mode, auto: core.auto, modes: core.thermal.modes || [], gmode: core.gmode,
                 boostPct: core.boostPct, temps: core.thermal.temps || {},
                 fans: core.fans.map(function(f) { return { label: f.label, rpm: f.rpm, boostPct: f.boost_pct } }) },
      powerButton: core.powerSaved
    }
  }

  // Agents: quickshell ipc -p /usr/share/omarchy/shell call mothership <fn> [args]
  IpcHandler {
    target: "mothership"
    function state(): string { return JSON.stringify(root.snapshot()) }
    function effect(name: string): string { return core.setEffect(name) }
    function color(hex: string): string { return core.setColor(hex) }
    function brightness(value: int): string { return core.setBrightness(value) }
    function mode(name: string): string { return core.setMode(name) }
    function gmode(): string { return core.toggleGmode() }
    function toggle(): void { root.toggle() }
    function openWindow(): void { root.openWindow() }
    function closeWindow(): void { root.windowOpen = false }
    function tcc(degrees: int): string { return core.setTcc(degrees) }
    function powerLimit(watts: int): string { return watts > 0 ? core.setPowerLimit(watts, core.mode) : core.setPowerLimit(null, core.mode) }
    function showTab(name: string): string {
      if (["keyboard", "chassis", "thermal", "power"].indexOf(name) < 0) return "tab is keyboard, chassis, thermal or power"
      root.tab = name
      root.open()
      return "ok"
    }
  }

  implicitWidth: shown ? button.implicitWidth : 0
  implicitHeight: button.implicitHeight
  visible: shown

  onOpenedChanged: if (opened) { core.refresh(); Qt.callLater(function() { keyCatcher.forceActiveFocus() }) }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "mothership"
    hasVisualContent: true
    labelVisible: false
    fixedWidth: root.vertical ? -1 : 18 + scaledHorizontalMargin * 2
    tooltipText: ""
    onPressed: function(b) { root.toggle() }

    Glyph {
      id: barGlyph
      anchors.centerIn: parent
      width: 18
      height: 18
      name: "flying-saucer-fill"
      color: core.daemonUp ? barColors.color : root.theme.dim(root.barForeground, 1.8)
      colors: core.daemonUp ? barColors.colors : []
      Behavior on color { ColorAnimation { duration: 400 } }

      SequentialAnimation on opacity {
        running: core.gmode && root.visible
        loops: Animation.Infinite
        alwaysRunToEnd: true
        NumberAnimation { from: 1; to: 0.45; duration: 1100; easing.type: Easing.InOutSine }
        NumberAnimation { from: 0.45; to: 1; duration: 1100; easing.type: Easing.InOutSine }
      }
    }
  }

  Loader {
    active: root.windowOpen
    sourceComponent: FullWindow {
      ship: core
      screen: button.QsWindow.window ? button.QsWindow.window.screen : null
      fontFamily: root.fontFamily
      onDismissed: root.windowOpen = false
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(460))
    // At most 80% of the screen; the tab area scrolls only past that.
    readonly property real maxCard: (panel.screenH > 0 ? panel.screenH : 1200) * 0.8
    contentHeight: panel.fittedContentHeight(column.implicitHeight, panel.maxCard)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: tabLoader.item && tabLoader.item.editing === true
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "1") root.tab = "keyboard"
        else if (t === "2") root.tab = "chassis"
        else if (t === "3") root.tab = "thermal"
        else if (t === "4") root.tab = "power"
        else if (t === "f" || t === "F") root.openWindow()
        else if (t === "g" || t === "G") core.toggleGmode()
      }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(14)

        // ---- header
        Item {
          width: parent.width
          height: 38
          Glyph {
            id: headGlyph
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 30; height: 30
            name: "flying-saucer-fill"
            color: core.daemonUp ? popupColors.color : root.theme.dim(Color.foreground, 1.8)
            colors: core.daemonUp ? popupColors.colors : []
          }
          Column {
            anchors.left: headGlyph.right
            anchors.leftMargin: 10
            anchors.right: fullButton.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            Text {
              text: "Mothership"
              color: Color.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
              font.weight: Font.DemiBold
            }
            Text {
              width: parent.width
              text: statusLine.text
              visible: text !== ""
              color: root.theme.dim(Color.foreground, 1.55)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
          }
          Chip {
            id: fullButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            text: "Full view"
            fontFamily: root.fontFamily
            onClicked: root.openWindow()
          }
        }

        // ---- the machine, with the keyboard brightness ruler beside it
        Item {
          width: parent.width
          height: mirror.implicitHeight
          visible: core.hasKeyboard || core.hasChassis || !core.loaded
          Mirror {
            id: mirror
            anchors.left: parent.left
            anchors.right: ruler.left
            anchors.rightMargin: 10
            compact: true
            live: root.opened
            keyboard: core.kb
            chassis: core.ch
            chassisKnown: core.chassisOk
          showTouchpad: core.hasTouchpad
          showHead: core.hasHead
          showRear: core.hasRear
          unlit: core.unlit
            powerColor: core.powerSaved[core.thermal.ac === false ? "dc-on" : "ac-full"] || ""
            onClicked: root.openWindow()
          }
          TickRuler {
            id: ruler
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -8
            vertical: true
            visible: core.hasKeyboard
            width: 22
            height: Math.max(80, mirror.height * 0.62)
            ticks: 21
            value: core.kb.brightness === undefined ? 100 : core.kb.brightness
            onReleased: function(v) { core.setBrightness(v) }
          }
          Text {
            anchors.horizontalCenter: ruler.horizontalCenter
            anchors.top: ruler.bottom
            anchors.topMargin: 6
            visible: core.hasKeyboard
            text: Math.round(ruler.liveValue) + "%"
            color: root.theme.dim(Color.foreground, 1.3)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.features: { "tnum": 1 }
          }
        }

        G.Segmented {
          width: parent.width
          fontFamily: root.fontFamily
          value: root.tab
          options: [{ value: "keyboard", label: "Keyboard" }, { value: "chassis", label: "Chassis" },
                    { value: "thermal", label: "Thermal" }, { value: "power", label: "Power" }]
          onPicked: function(v) { root.tab = v }
        }

        // Tabs scroll only when the screen is too short for them.
        Flickable {
          id: tabFlick
          width: parent.width
          readonly property real room: panel.maxCard - panel.verticalContentInset - y - (noticeBox.visible ? noticeBox.height + column.spacing : 0) - 2
          height: Math.max(140, Math.min(tabLoader.implicitHeight, room))
          contentHeight: tabLoader.implicitHeight
          clip: contentHeight > height
          interactive: contentHeight > height
          boundsBehavior: Flickable.StopAtBounds
          Loader {
            id: tabLoader
            width: parent.width
            sourceComponent: root.tab === "thermal" ? thermalTab : root.tab === "power" ? powerTab
                           : root.tab === "chassis" ? chassisTab : keyboardTab
          }
        }

        Notice {
          id: noticeBox
          width: parent.width
          fontFamily: root.fontFamily
          urgent: core.error !== ""
          text: core.error !== "" ? core.error : core.problems.join(" ")
        }
      }
    }
  }

  Component {
    id: keyboardTab
    KeyboardTab { ship: core; fontFamily: root.fontFamily }
  }
  Component {
    id: chassisTab
    ChassisTab { ship: core; fontFamily: root.fontFamily }
  }
  Component {
    id: thermalTab
    ThermalTab { ship: core; fontFamily: root.fontFamily }
  }
  Component {
    id: powerTab
    PowerTab { ship: core; fontFamily: root.fontFamily }
  }
}

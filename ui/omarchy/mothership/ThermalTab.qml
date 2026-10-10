import QtQuick
import qs.Commons
import qs.Ui
import "../../gage-ui" as G

// Thermal: the hottest sensor as a ring next to a list of temperatures and fans (each with a
// thin status bar), then the automatic rules, the mode and the fan boost.
Column {
  id: tab
  required property var ship
  property string fontFamily: Style.font.family
  property real ringSize: 104

  property G.Theme theme: G.Theme {}
  property bool advancedOpen: false
  spacing: 14

  readonly property var th: ship.thermal
  readonly property var temps: th.temps || {}
  readonly property bool gpuAwake: !!(th.dgpu && th.dgpu.state === "active")
  readonly property var labels: ({
    "low-power": "Battery", "quiet": "Quiet", "balanced": "Balanced",
    "balanced-performance": "Fast", "performance": "G-Mode"
  })
  readonly property var order: ["low-power", "quiet", "balanced", "balanced-performance", "performance"]
  readonly property var modeOptions: order.filter(function(m) { return (tab.th.modes || []).indexOf(m) >= 0 })
                                          .map(function(m) { return { value: m, label: tab.labels[m] } })

  // The hottest sensor leads the ring.
  readonly property var hottest: {
    var c = [{ label: "Package", v: temps["package"] }, { label: "CPU", v: temps.cpu },
             { label: "GPU", v: gpuAwake ? (th.dgpu.temp !== undefined ? th.dgpu.temp : temps.gpu) : null }]
    var best = { label: "Package", v: null }
    c.forEach(function(x) { if (x.v !== null && x.v !== undefined && (best.v === null || x.v > best.v)) best = x })
    return best
  }

  // The adapter, from the extended driver (power_info); "" when it doesn't report one.
  readonly property var adapter: th.power_info || null
  readonly property bool adapterOk: !adapter || !adapter.status || adapter.status === "ok"
  readonly property string adapterText: {
    var a = adapter
    if (!a) return ""
    var w = a.watts && a.watts.length ? a.watts.join(" + ") + " W" : ""
    if (!a.status || a.status === "ok") return w ? w + (a.watts.length > 1 ? " adapters" : " adapter") : ""
    if (a.status === "undersized") return (w ? "The " + w + " adapter" : "The adapter") + " is too small for full performance; the CPU and GPU are held back."
    if (a.status === "unsupported") return "The adapter isn't recognised, so performance may be limited. Use the one that came with the laptop."
    return "The adapter reports status " + a.status + "."
  }

  // Power limit for the current mode: the mode's own, else the one for every mode.
  readonly property var limits: ship.powerLimits
  readonly property var modeLimit: limits[ship.mode] !== undefined ? limits[ship.mode] : null
  readonly property var allLimit: limits.all !== undefined ? limits.all : null
  readonly property var activeLimit: modeLimit !== null ? modeLimit : allLimit
  readonly property var now: ship.powerNow || {}

  function heat(v) {
    if (v === null || v === undefined) return theme.dim(Color.foreground, 1.55)
    var c = v >= 92 ? theme.red : v >= 80 ? theme.orange : v >= 65 ? theme.yellow : theme.green
    return theme.light ? Qt.darker(c, 1.3) : c
  }
  function fanName(f, i) {
    var base = String(f.label || "Fan").replace(/\s*fan$/i, "")
    var all = ship.fans, before = 0, total = 0
    for (var k = 0; k < all.length; k++) {
      if (all[k].label !== f.label) continue
      total++
      if (k < i) before++
    }
    return (total < 2 ? base : base + " " + (before + 1)) + " fan"
  }

  readonly property var metrics: {
    var m = [
      { label: "CPU", text: temps.cpu === undefined || temps.cpu === null ? "—" : Math.round(temps.cpu) + "°", frac: (temps.cpu || 0) / 100, color: heat(temps.cpu) },
      { label: "GPU", text: gpuAwake ? Math.round(th.dgpu.temp) + "°" : "Asleep",
        frac: gpuAwake ? th.dgpu.temp / 100 : 0, color: gpuAwake ? heat(th.dgpu.temp) : theme.dim(Color.foreground, 1.55) }
    ]
    var fans = ship.fans
    for (var i = 0; i < fans.length; i++) {
      var f = fans[i], top = Math.max(f.max || 0, f.rpm, 1000)
      m.push({ label: fanName(f, i), text: f.rpm >= 1000 ? (f.rpm / 1000).toFixed(1) + "k rpm" : f.rpm + " rpm",
               frac: f.rpm / top, color: ship.gmode ? Color.urgent : Color.accent })
    }
    return m
  }

  Text {
    width: parent.width
    visible: tab.ship.loaded && !tab.ship.hasThermal
    text: "No thermal controls here: the alienware-wmi platform profile isn't loaded."
    color: tab.theme.dim(Color.foreground, 1.55)
    font.family: tab.fontFamily
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }

  // ---- score ring + metrics
  Item {
    width: parent.width
    height: Math.max(ringCol.height, list.height)
    visible: tab.ship.hasThermal

    Column {
      id: ringCol
      width: tab.ringSize + 8
      spacing: 12
      G.Ring {
        width: tab.ringSize
        height: tab.ringSize
        anchors.horizontalCenter: parent.horizontalCenter
        stroke: 7
        value: (tab.hottest.v || 0) / 100
        color: tab.heat(tab.hottest.v)
        Column {
          anchors.centerIn: parent
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: tab.hottest.v === null ? "—" : Math.round(tab.hottest.v) + "°"
            color: Color.foreground
            font.family: tab.fontFamily
            font.pixelSize: Math.round(tab.ringSize * 0.27)
            font.weight: Font.DemiBold
            font.features: { "tnum": 1 }
          }
          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: tab.hottest.label
            color: tab.theme.dim(Color.foreground, 1.45)
            font.family: tab.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
      // The current mode as a pill; G-Mode glows.
      Item {
        anchors.horizontalCenter: parent.horizontalCenter
        width: pill.width
        height: pill.height
        visible: tab.ship.mode !== ""
        Rectangle {
          anchors.centerIn: parent
          width: pill.width + 10
          height: pill.height + 10
          radius: height / 2
          color: Util.alpha(Color.urgent, 0.16)
          visible: tab.ship.gmode
          SequentialAnimation on opacity {
            running: tab.ship.gmode && tab.visible
            loops: Animation.Infinite
            NumberAnimation { from: 1; to: 0.15; duration: 1100; easing.type: Easing.InOutSine }
            NumberAnimation { from: 0.15; to: 1; duration: 1100; easing.type: Easing.InOutSine }
          }
        }
        Rectangle {
          id: pill
          width: pillText.implicitWidth + 20
          height: 22
          radius: 11
          color: tab.ship.gmode ? Util.alpha(Color.urgent, 0.2) : Util.alpha(Color.foreground, 0.07)
          border.width: 1
          border.color: tab.ship.gmode ? Util.alpha(Color.urgent, 0.85) : tab.theme.ink(0.1)
          Text {
            id: pillText
            anchors.centerIn: parent
            text: tab.labels[tab.ship.mode] || tab.ship.mode
            color: tab.ship.gmode ? Color.urgent : Color.foreground
            font.family: tab.fontFamily
            font.pixelSize: Style.font.caption
            font.weight: Font.DemiBold
          }
        }
      }
    }

    Column {
      id: list
      anchors.left: ringCol.right
      anchors.leftMargin: 18
      anchors.right: parent.right
      spacing: 8
      Repeater {
        model: tab.metrics
        Column {
          required property var modelData
          width: list.width
          spacing: 4
          Item {
            width: parent.width
            height: mLabel.implicitHeight
            Text {
              id: mLabel
              text: modelData.label
              color: tab.theme.dim(Color.foreground, 1.4)
              font.family: tab.fontFamily
              font.pixelSize: Style.font.caption
            }
            Text {
              anchors.right: parent.right
              text: modelData.text
              color: Color.foreground
              font.family: tab.fontFamily
              font.pixelSize: Style.font.caption
              font.weight: Font.DemiBold
              font.features: { "tnum": 1 }
            }
          }
          Rectangle {
            width: parent.width
            height: 3
            radius: 1.5
            color: tab.theme.ink(0.08)
            Rectangle {
              width: parent.width * Math.max(0, Math.min(1, modelData.frac))
              height: parent.height
              radius: 1.5
              color: modelData.color
              Behavior on width { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
            }
          }
        }
      }
    }
  }

  // ---- automatic
  Item {
    width: parent.width
    height: Math.max(autoSwitch.implicitHeight, autoText.implicitHeight)
    visible: tab.ship.hasThermal
    Column {
      id: autoText
      anchors.left: parent.left
      anchors.right: autoSwitch.left
      anchors.rightMargin: 8
      anchors.verticalCenter: parent.verticalCenter
      Text {
        text: "Automatic"
        color: Color.foreground
        font.family: tab.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width
        text: tab.ship.auto ? "Balanced plugged in, Quiet on battery, G-Mode when it runs hot."
                            : "The mode and boost stay where you put them."
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
    ToggleSwitch {
      id: autoSwitch
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      cursorRing: false
      checked: tab.ship.auto
      onToggled: tab.ship.setAuto(!checked)
    }
  }

  G.Segmented {
    width: parent.width
    visible: tab.ship.hasThermal && tab.modeOptions.length > 0
    fontFamily: tab.fontFamily
    value: tab.ship.mode
    options: tab.modeOptions
    onPicked: function(v) { tab.ship.setMode(v) }
  }

  Column {
    width: parent.width
    spacing: 6
    visible: tab.ship.hasThermal && tab.ship.fans.length > 0
    Heading {
      width: parent.width
      text: "Fan boost"
      value: Math.round(boost.liveValue) + "%"
      fontFamily: tab.fontFamily
    }
    TickRuler {
      id: boost
      width: parent.width
      value: tab.ship.boostPct
      tint: Qt.tint(Color.foreground, Util.alpha(Color.urgent, boost.liveValue / 100 * 0.7))
      onReleased: function(v) { tab.ship.setBoost(v) }
    }
    Text {
      width: parent.width
      visible: tab.ship.auto
      text: "Automatic raises this as the CPU warms up; moving it turns Automatic off."
      color: tab.theme.dim(Color.foreground, 1.55)
      font.family: tab.fontFamily
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
    }
  }

  // ---- adapter trouble shows outside Advanced
  Notice {
    width: parent.width
    visible: text !== ""
    urgent: true
    fontFamily: tab.fontFamily
    text: tab.adapterOk ? "" : tab.adapterText
  }

  // ---- advanced
  Rectangle {
    width: parent.width
    height: 1
    color: tab.theme.ink(0.08)
    visible: advHeader.visible
  }

  Item {
    id: advHeader
    width: parent.width
    height: 26
    visible: tab.ship.hasThermal && (tab.ship.tcc !== null || tab.ship.powerNow !== null || tab.adapter !== null)
    Glyph {
      id: caret
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: 12; height: 12
      name: tab.advancedOpen ? "caret-down" : "caret-right"
      color: tab.theme.dim(Color.foreground, 1.4)
    }
    Text {
      anchors.left: caret.right
      anchors.leftMargin: 8
      anchors.verticalCenter: parent.verticalCenter
      text: "Advanced"
      color: Color.foreground
      font.family: tab.fontFamily
      font.pixelSize: Style.font.body
    }
    Text {
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      text: {
        var p = []
        if (tab.ship.tcc) p.push("Throttles " + tab.ship.tcc + " \u00b0C earlier")
        if (tab.activeLimit !== null) p.push(tab.activeLimit + " W limit")
        return p.join(" \u00b7 ")
      }
      color: tab.theme.dim(Color.foreground, 1.55)
      font.family: tab.fontFamily
      font.pixelSize: Style.font.caption
    }
    MouseArea {
      anchors.fill: parent
      cursorShape: Qt.PointingHandCursor
      onClicked: tab.advancedOpen = !tab.advancedOpen
    }
  }

  Column {
    width: parent.width
    spacing: 16
    visible: advHeader.visible && tab.advancedOpen

    // Temperature limit (TCC offset)
    Column {
      width: parent.width
      spacing: 6
      visible: tab.ship.tcc !== null
      Heading {
        width: parent.width
        text: "Temperature limit"
        value: tccRuler.liveValue > 0 ? "\u2212" + Math.round(tccRuler.liveValue) + " \u00b0C" : "Normal"
        fontFamily: tab.fontFamily
      }
      TickRuler {
        id: tccRuler
        width: parent.width
        minimum: 0
        maximum: 15
        step: 1
        ticks: 46
        majorEvery: 15
        value: tab.ship.tcc || 0
        onReleased: function(v) { tab.ship.setTcc(v) }
      }
      Text {
        width: parent.width
        text: tccRuler.liveValue > 0 ? "Throttle " + Math.round(tccRuler.liveValue) + " \u00b0C earlier (cooler and quieter)."
                                     : "The CPU throttles at its normal temperature."
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }

    // Power limit (CPU package, per thermal mode)
    Column {
      width: parent.width
      spacing: 6
      visible: tab.ship.powerNow !== null
      Heading {
        width: parent.width
        text: "Power limit"
        value: powerRuler.dragging ? Math.round(powerRuler.liveValue) + " W"
             : tab.activeLimit !== null ? tab.activeLimit + " W" : "Firmware default"
        fontFamily: tab.fontFamily
      }
      TickRuler {
        id: powerRuler
        width: parent.width
        minimum: 15
        maximum: 195
        step: 5
        ticks: 37
        majorEvery: 4
        tint: tab.activeLimit !== null || powerRuler.dragging ? Color.foreground : tab.theme.dim(Color.foreground, 1.6)
        value: Math.max(15, Math.min(195, tab.activeLimit !== null ? tab.activeLimit : (tab.now.long_term || 45)))
        onReleased: function(v) { tab.ship.setPowerLimit(v, tab.ship.mode) }
      }
      Text {
        width: parent.width
        text: {
          var m = tab.labels[tab.ship.mode] || tab.ship.mode
          var scope = tab.modeLimit !== null ? "For " + m + " mode." : tab.allLimit !== null ? "For every mode." : "Drag to cap the CPU in " + m + " mode."
          var cur = tab.now.long_term ? " Now " + tab.now.long_term + " W sustained" + (tab.now.short_term ? ", " + tab.now.short_term + " W in bursts." : ".") : ""
          return scope + cur
        }
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
      Row {
        spacing: 8
        Chip {
          text: "Firmware default"
          fontFamily: tab.fontFamily
          selected: tab.activeLimit === null
          onClicked: {
            if (tab.modeLimit !== null) tab.ship.setPowerLimit(null, tab.ship.mode)
            if (tab.allLimit !== null) tab.ship.setPowerLimit(null, null)
          }
        }
        Chip {
          visible: tab.modeLimit !== null && tab.modeLimit !== tab.allLimit
          text: "Use for every mode"
          fontFamily: tab.fontFamily
          onClicked: tab.ship.setPowerLimit(tab.modeLimit, null)
        }
      }
    }

    // Adapter, quietly, when it's fine.
    Item {
      width: parent.width
      height: adapterLine.implicitHeight
      visible: tab.adapterOk && tab.adapterText !== ""
      Glyph {
        id: plugIcon
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 14; height: 14
        name: "plug"
        color: tab.theme.dim(Color.foreground, 1.55)
      }
      Text {
        id: adapterLine
        anchors.left: plugIcon.right
        anchors.leftMargin: 7
        text: tab.adapterText + (tab.th.ac === false ? " (on battery now)" : "")
        color: tab.theme.dim(Color.foreground, 1.55)
        font.family: tab.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}

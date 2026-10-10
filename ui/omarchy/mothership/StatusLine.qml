import QtQuick

// One plain line about the hardware: firmware versions and what's missing.
QtObject {
  required property var ship
  readonly property string text: {
    var st = ship.status || {}, parts = []
    if (!ship.loaded) return ship.error !== "" ? "" : "Connecting to mothershipd…"
    if (st.keyboard && st.keyboard.firmware) parts.push("Keyboard firmware " + st.keyboard.firmware)
    else if (!ship.hasKeyboard) parts.push("No per-key keyboard")
    if (st.chassis && st.chassis.firmware) parts.push("Lights firmware " + st.chassis.firmware)
    if (ship.hasThermal) parts.push(ship.thermal.ac === false ? "On battery" : "Plugged in")
    return parts.join(" · ")
  }
}

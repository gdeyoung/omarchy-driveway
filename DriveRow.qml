import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// One drive row: kind glyph, name, usage bar, action buttons, busy /
// pending-upload notices, expandable info (Model.infoRows).
// Card body derived from jgarza9788/drives DriveCard.qml @ 255609e (MIT).
CursorSurface {
  id: row
  property var drive: null
  property var busyResult: null
  property bool showInfo: false
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property string fontFamily: Style.font.family
  property int fullWarnPct: 90

  signal openRequested()
  signal terminalRequested()
  signal ejectRequested(bool kill, bool force)
  signal mountRequested()
  signal unlockRequested()
  signal infoToggled()

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property bool full: drive && drive.mounted && drive.size > 0 && drive.pct >= fullWarnPct
  readonly property bool isSystem: drive && drive.kind === "system"
  readonly property string caption: drive
    ? [Model.kindName(drive), Model.usageText(drive), drive.fstype]
        .filter(function(s) { return !!s }).join(" · ")
    : ""

  foreground: row.foreground
  fill: Qt.rgba(1, 1, 1, 0.04)
  radius: Style.cornerRadius
  implicitHeight: content.implicitHeight + Style.space(16)

  Column {
    id: content
    width: parent.width
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(6)

    Row {
      width: parent.width
      spacing: Style.space(10)

      Text {
        text: drive ? Model.kindIcon(drive, null) : ""
        color: drive && drive.mounted ? row.foreground : row.dim
        font.family: row.fontFamily
        font.pixelSize: Style.font.heading
        anchors.verticalCenter: parent.verticalCenter
      }

      Column {
        width: parent.width - Style.space(52) - actionsRow.implicitWidth
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: drive ? (drive.label || drive.name || Model.kindName(drive)) : ""
          color: row.foreground
          font.family: row.fontFamily
          font.pixelSize: Style.font.body
          font.bold: row.isSystem
          elide: Text.ElideRight
        }

        Text {
          width: parent.width
          visible: text !== ""
          textFormat: Text.PlainText
          text: row.caption
          color: row.dim
          font.family: row.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }

        // Usage bar
        Rectangle {
          width: parent.width
          height: Style.space(4)
          radius: height / 2
          visible: drive && drive.size > 0
          color: Qt.alpha(row.dim, 0.35)

          Rectangle {
            width: parent.width * Math.min(1, (drive ? drive.pct : 0) / 100)
            height: parent.height
            radius: parent.radius
            color: row.full ? row.urgent : Qt.alpha(row.foreground, 0.75)
          }
        }
      }

      Row {
        id: actionsRow
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)

        RowButton {
            visible: !row.isSystem && !drive.mounted && !drive.locked
          glyph: "󰐘"
          tooltip: "Mount"
          fontFamily: row.fontFamily
          foreground: row.foreground
          onActivated: row.mountRequested()
        }

        RowButton {
          visible: !row.isSystem && drive.locked
          glyph: "󰌋"
          tooltip: "Unlock (LUKS passphrase in a terminal)"
          fontFamily: row.fontFamily
          foreground: row.foreground
          onActivated: row.unlockRequested()
        }

        RowButton {
          visible: drive.mounted
          glyph: "󰝰"
          tooltip: "Open in file manager"
          fontFamily: row.fontFamily
          foreground: row.foreground
          onActivated: row.openRequested()
        }

        RowButton {
          visible: drive.mounted
          glyph: "󰆍"
          tooltip: "Open a terminal here"
          fontFamily: row.fontFamily
          foreground: row.foreground
          onActivated: row.terminalRequested()
        }

        RowButton {
          visible: !row.isSystem && drive.mounted && !!drive.eject
          glyph: drive.removable ? "󰒍" : "󰅖"
          tooltip: drive.removable ? "Eject (power off)" : "Unmount"
          fontFamily: row.fontFamily
          foreground: row.foreground
          onActivated: row.ejectRequested(false)
        }

        RowButton {
          visible: !row.isSystem
          glyph: "󰭚"
          tooltip: "Details"
          fontFamily: row.fontFamily
          foreground: row.showInfo ? row.foreground : row.dim
          onActivated: row.infoToggled()
        }
      }
    }

    // Busy / pending-upload notice with the one remedy that can work.
    Column {
      width: parent.width
      visible: !!row.busyResult
      spacing: Style.space(4)

      Text {
        width: parent.width
        visible: !!row.busyResult
        textFormat: Text.PlainText
        wrapMode: Text.WordWrap
        text: row.busyResult ? row.busyResult.message : ""
        color: row.urgent
        font.family: row.fontFamily
        font.pixelSize: Style.font.caption
      }

      RowButton {
        visible: row.busyResult && row.busyResult.procs && row.busyResult.procs.length > 0
        label: "Close apps & retry"
        fontFamily: row.fontFamily
        foreground: row.foreground
        onActivated: row.ejectRequested(true, false)
      }

      RowButton {
        visible: row.busyResult && row.busyResult.uploads > 0
        label: "Unmount anyway"
        fontFamily: row.fontFamily
        foreground: row.foreground
        onActivated: row.ejectRequested(false, true)
      }
    }

    // Info rows
    Column {
      width: parent.width
      visible: row.showInfo
      spacing: Style.space(2)

      Repeater {
        model: row.showInfo && drive ? Model.infoRows(drive) : []
        Row {
          width: content.width
          required property var modelData
          spacing: Style.space(8)

          Text {
            text: modelData[0]
            color: row.dim
            font.family: row.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignLeft
          }
          Text {
            width: parent.width - Style.space(90)
            textFormat: Text.PlainText
            text: modelData[1]
            color: row.foreground
            font.family: row.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideMiddle
            horizontalAlignment: Text.AlignRight
          }
        }
      }
    }
  }
}

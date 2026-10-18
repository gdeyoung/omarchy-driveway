import QtQuick
import qs.Commons
import qs.Ui

// General settings: the user-facing subset of the manifest schema, editable
// in-panel (Omarchy renders no schema UI of its own).  Same inline-view
// contract as CacheSettings: height = implicitHeight, closed() returns to the
// tab column.  Every control applies immediately through service.saveSetting,
// which serializes + confirms writes (powercore pattern) — the displayed value
// always reflects confirmed state, so a failed write leaves the UI truthful.
Column {
  id: gen

  property color foreground: "#fff"
  property color urgent: "#f66"
  property string fontFamily: "sans"
  property var service: null
  signal closed()

  width: parent ? parent.width : 0
  spacing: Style.space(10)

  Text {
    width: parent.width
    text: "Settings"
    color: gen.foreground
    font.family: gen.fontFamily
    font.pixelSize: Style.font.subTitle
    font.weight: Font.Bold
  }

  // ── refresh interval ─────────────────────────────────────────────
  Row {
    width: parent.width
    spacing: Style.space(8)

    Text {
      id: pollLabel
      text: "Refresh every"
      color: gen.foreground
      font.family: gen.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - pollDown.width - pollUp.width - pollVal.width
              - parent.spacing * 3
      elide: Text.ElideRight
    }

    CursorSurface {
      id: pollDown
      foreground: gen.foreground
      bordered: true
      radius: Style.cornerRadius
      implicitHeight: pollVal.implicitHeight + Style.space(6)
      width: pollDownText.implicitWidth + Style.space(16)

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          var next = Math.max(2, gen.service.pollSec - 5)
          if (next !== gen.service.pollSec) gen.service.saveSetting("pollIntervalSec", next)
        }
      }
      Text {
        id: pollDownText
        anchors.centerIn: parent
        text: "−"
        color: gen.foreground
        font.family: gen.fontFamily
        font.pixelSize: Style.font.body
      }
    }

    Text {
      id: pollVal
      text: service ? service.pollSec + "s" : ""
      color: gen.foreground
      font.family: gen.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignHCenter
    }

    CursorSurface {
      id: pollUp
      foreground: gen.foreground
      bordered: true
      radius: Style.cornerRadius
      implicitHeight: pollVal.implicitHeight + Style.space(6)
      width: pollUpText.implicitWidth + Style.space(16)

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          var next = Math.min(300, gen.service.pollSec + 5)
          if (next !== gen.service.pollSec) gen.service.saveSetting("pollIntervalSec", next)
        }
      }
      Text {
        id: pollUpText
        anchors.centerIn: parent
        text: "+"
        color: gen.foreground
        font.family: gen.fontFamily
        font.pixelSize: Style.font.body
      }
    }
  }

  Text {
    width: parent.width
    wrapMode: Text.Wrap
    color: Qt.alpha(gen.foreground, 0.7)
    font.family: gen.fontFamily
    font.pixelSize: Style.font.caption
    text: "Plugging a drive in always refreshes instantly; this is the background poll."
  }

  // ── toggles ──────────────────────────────────────────────────────
  Repeater {
    model: [
      { key: "showNetwork", label: "Show network & cloud drives",
        help: "NFS/SMB/sshfs shares and rclone mounts in the Drives tab." },
      { key: "showUnmounted", label: "Show unmounted drives",
        help: "Plugged-in drives that aren't mounted yet, with a Mount button." }
    ]

    delegate: Column {
      id: del
      required property var modelData
      width: gen.width
      spacing: Style.space(4)

      Row {
        width: parent.width
        spacing: Style.space(8)

        Text {
          text: del.modelData.label
          color: gen.foreground
          font.family: gen.fontFamily
          font.pixelSize: Style.font.body
          anchors.verticalCenter: parent.verticalCenter
          width: parent.width - toggleBtn.width - parent.spacing
          elide: Text.ElideRight
        }

        CursorSurface {
          id: toggleBtn
          foreground: gen.foreground
          bordered: true
          radius: Style.cornerRadius
          implicitHeight: toggleText.implicitHeight + Style.space(8)
          width: toggleText.implicitWidth + Style.space(20)

          MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: gen.service.saveSetting(
              del.modelData.key, !gen.service.settingBool(del.modelData.key))
          }
          Text {
            id: toggleText
            anchors.centerIn: parent
            text: gen.service && gen.service.settingBool(del.modelData.key) ? "On" : "Off"
            color: gen.foreground
            font.family: gen.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }

      Text {
        width: parent.width
        wrapMode: Text.Wrap
        color: Qt.alpha(gen.foreground, 0.7)
        font.family: gen.fontFamily
        font.pixelSize: Style.font.caption
        text: del.modelData.help
      }
    }
  }

  // ── nearly-full threshold ────────────────────────────────────────
  Row {
    width: parent.width
    spacing: Style.space(8)

    Text {
      id: warnLabel
      text: "Drives look nearly-full at"
      color: gen.foreground
      font.family: gen.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - warnDown.width - warnUp.width - warnVal.width
              - parent.spacing * 3
      elide: Text.ElideRight
    }

    CursorSurface {
      id: warnDown
      foreground: gen.foreground
      bordered: true
      radius: Style.cornerRadius
      implicitHeight: warnVal.implicitHeight + Style.space(6)
      width: warnDownText.implicitWidth + Style.space(16)

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          var next = Math.max(50, gen.service.fullWarnPct - 5)
          if (next !== gen.service.fullWarnPct) gen.service.saveSetting("fullWarnPct", next)
        }
      }
      Text {
        id: warnDownText
        anchors.centerIn: parent
        text: "−"
        color: gen.foreground
        font.family: gen.fontFamily
        font.pixelSize: Style.font.body
      }
    }

    Text {
      id: warnVal
      text: service ? service.fullWarnPct + "%" : ""
      color: gen.foreground
      font.family: gen.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
      horizontalAlignment: Text.AlignHCenter
    }

    CursorSurface {
      id: warnUp
      foreground: gen.foreground
      bordered: true
      radius: Style.cornerRadius
      implicitHeight: warnVal.implicitHeight + Style.space(6)
      width: warnUpText.implicitWidth + Style.space(16)

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          var next = Math.min(100, gen.service.fullWarnPct + 5)
          if (next !== gen.service.fullWarnPct) gen.service.saveSetting("fullWarnPct", next)
        }
      }
      Text {
        id: warnUpText
        anchors.centerIn: parent
        text: "+"
        color: gen.foreground
        font.family: gen.fontFamily
        font.pixelSize: Style.font.body
      }
    }
  }

  // ── back ─────────────────────────────────────────────────────────
  CursorSurface {
    width: parent.width
    foreground: gen.foreground
    bordered: true
    radius: Style.cornerRadius
    implicitHeight: backLabel.implicitHeight + Style.space(12)

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: gen.closed()
    }
    Text {
      id: backLabel
      anchors.centerIn: parent
      text: "󰅁  Back to drives"
      color: gen.foreground
      font.family: gen.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}

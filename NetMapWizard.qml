import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui
import "Model.js" as Model

// gdeyoung.driveway network map wizard — browse the LAN (avahi) or paste a
// URL, then mount via gio. Credentials ride stdin into the CLI, never argv.
Rectangle {
  id: wiz
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property string fontFamily: Style.font.family
  property var service: null            // the Service instance (drv)
  signal closed()

  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property var schemes: ["smb", "sftp", "ftp", "nfs", "dav"]
  readonly property var schemeGlyphs: ({ smb: "󰅹", sftp: "󰣀", ftp: "󰢑",
                                         nfs: "󰛧", dav: "󰕮" })
  readonly property var schemeLabels: ({ smb: "Samba", sftp: "SSH", ftp: "FTP",
                                         nfs: "NFS", dav: "WebDAV" })

  property string mode: "browse"        // browse | manual
  property string browseStep: "servers" // servers | shares | creds
  property string pendingServer: ""
  property string pendingScheme: "smb"
  property string pendingShare: ""
  property int manualSchemeIndex: 0

  color: "transparent"
  radius: Style.cornerRadius
  readonly property real contentHeight: wizCol.implicitHeight

  function open() {
    mode = "browse"; browseStep = "servers"; pendingServer = ""; pendingShare = ""
    wiz.manualSchemeIndex = 0
    if (service && service.netServers.length === 0) service.netDiscover()
  }

  function pickServer(server, scheme) {
    pendingServer = server
    pendingScheme = scheme
    browseStep = "shares"
    service.netBrowseShares(server, "", "", "")
  }

  function openCredsFor(server) {
    // server refused guest listing: jump straight to credentials
    pendingServer = server
    pendingScheme = "smb"
    browseStep = "creds"
  }

  function pickShare(share) {
    pendingShare = share
    browseStep = "creds"
  }

  function mapFromBrowse() {
    service.netMap({ scheme: pendingScheme, server: pendingServer,
                     share: pendingShare, user: userField.text || null,
                     domain: domainField.text || null,
                     password: passField.text || null, save: true })
  }

  function mapFromManual() {
    var spec = { scheme: schemes[wiz.manualSchemeIndex],
                 server: manualServer.text.trim(), save: true }
    if (manualShare.text.trim()) spec.share = manualShare.text.trim()
    if (manualPort.text.trim()) spec.port = Number(manualPort.text.trim())
    if (manualUser.text.trim()) spec.user = manualUser.text.trim()
    if (manualPass.text.trim()) spec.password = manualPass.text.trim()
    service.netMap(spec)
  }

  Column {
    id: wizCol
    anchors.fill: parent
    spacing: Style.space(8)

    Row {
      width: parent.width
      spacing: Style.space(8)

      Text {
        text: "Map network drive"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.heading
        anchors.verticalCenter: parent.verticalCenter
      }
      Item { width: Style.space(8); height: 1; anchors.verticalCenter: parent.verticalCenter }
      RowButton { glyph: ""; foreground: wiz.foreground; fontFamily: wiz.fontFamily
                  tooltip: "Close"; onActivated: wiz.closed() }
    }

    Row {
      spacing: Style.space(6)
      Repeater {
        model: ["browse", "manual"]
        Rectangle {
          required property string modelData
          readonly property bool active: wiz.mode === modelData
          width: modeLabel.implicitWidth + Style.space(20)
          height: Style.space(26)
          radius: height / 2
          color: active ? Qt.alpha(wiz.foreground, 0.16) : Qt.alpha(wiz.foreground, 0.05)
          Text {
            id: modeLabel
            anchors.centerIn: parent
            text: modelData === "browse" ? "Browse LAN" : "Manual"
            color: active ? wiz.foreground : wiz.dim
            font.family: wiz.fontFamily
            font.pixelSize: Style.font.caption
          }
          MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                      onClicked: wiz.mode = modelData }
        }
      }
    }

    // ---- browse mode ----
    Column {
      visible: wiz.mode === "browse"
      width: parent.width
      spacing: Style.space(6)

      Row {
        visible: wiz.browseStep !== "servers"
        spacing: Style.space(6)
        RowButton { label: "← Servers"; foreground: wiz.foreground; fontFamily: wiz.fontFamily
                    onActivated: { wiz.browseStep = "servers"; wiz.pendingShare = "" } }
      }

      BusyIndicator {
        visible: (wiz.service && wiz.service.netDiscovering) ||
                 (wiz.service && wiz.service.netListingShares)
        running: visible
        width: Style.space(28); height: Style.space(28)
        anchors.horizontalCenter: parent.horizontalCenter
      }

      Text {
        visible: wiz.browseStep === "servers" && !wiz.service.netDiscovering &&
                 wiz.service.netServers.length === 0
        width: parent.width
        wrapMode: Text.WordWrap
        text: "No SMB/SSH/FTP servers found on the LAN yet. Discovery takes a few seconds — or use Manual."
        color: wiz.dim
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.caption
        horizontalAlignment: Text.AlignHCenter
      }

      Repeater {
        model: wiz.browseStep === "servers" ? wiz.service.netServers : []
        Rectangle {
          required property var modelData
          width: parent.width
          height: Style.space(34)
          radius: Style.cornerRadius
          color: serverMouse.containsMouse ? Qt.alpha(wiz.foreground, 0.10) : Qt.rgba(1, 1, 1, 0.04)
          Row {
            anchors.fill: parent
            anchors.margins: Style.space(8)
            spacing: Style.space(8)
            Text {
              text: wiz.schemeGlyphs[modelData.scheme] || "󰲂"
              color: wiz.foreground
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              text: modelData.name
              color: wiz.foreground
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
              width: parent.width * 0.45
            }
            Text {
              text: modelData.kind + " · " + modelData.host
              color: wiz.dim
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.caption
              anchors.verticalCenter: parent.verticalCenter
              elide: Text.ElideRight
              width: parent.width * 0.4
            }
          }
          MouseArea {
            id: serverMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: wiz.pickServer(modelData.host, modelData.scheme)
          }
        }
      }

      Text {
        visible: wiz.browseStep === "shares"
        width: parent.width
        text: wiz.service.netSharesServer
        color: wiz.dim
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.caption
      }

      Repeater {
        model: wiz.browseStep === "shares" ? wiz.service.netShares : []
        Rectangle {
          required property var modelData
          width: parent.width
          height: Style.space(32)
          radius: Style.cornerRadius
          color: shareMouse.containsMouse ? Qt.alpha(wiz.foreground, 0.10) : Qt.rgba(1, 1, 1, 0.04)
          Text {
            anchors.left: parent.left
            anchors.leftMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            text: "  " + modelData.name
            color: wiz.foreground
            font.family: wiz.fontFamily
            font.pixelSize: Style.font.body
          }
          MouseArea {
            id: shareMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: wiz.pickShare(modelData.name)
          }
        }
      }

      // ---- credentials step (shared with needs-creds flow) ----
      Column {
        visible: wiz.browseStep === "creds"
        width: parent.width
        spacing: Style.space(6)

        Text {
          width: parent.width
          text: wiz.pendingShare !== ""
            ? wiz.pendingScheme.toUpperCase() + "  " + wiz.pendingServer + "/" + wiz.pendingShare
            : "Login for " + wiz.pendingServer
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
        }
        TextField {
          id: userField
          width: parent.width
          placeholderText: "User (blank for guest/default)"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
          background: Rectangle { radius: Style.cornerRadius
                                  color: Qt.alpha(wiz.foreground, 0.06) }
        }
        TextField {
          id: domainField
          visible: wiz.pendingScheme === "smb"
          width: parent.width
          placeholderText: "Domain (usually not needed)"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
          background: Rectangle { radius: Style.cornerRadius
                                  color: Qt.alpha(wiz.foreground, 0.06) }
        }
        TextField {
          id: passField
          width: parent.width
          echoMode: TextInput.Password
          placeholderText: "Password (blank if none)"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
          background: Rectangle { radius: Style.cornerRadius
                                  color: Qt.alpha(wiz.foreground, 0.06) }
        }
        CursorSurface {
          width: parent.width
          foreground: wiz.foreground
          fill: Qt.rgba(1, 1, 1, 0.08)
          radius: Style.cornerRadius
          implicitHeight: mapLabel.implicitHeight + Style.space(12)
          Text {
            id: mapLabel
            anchors.centerIn: parent
            text: wiz.service.netMounting ? "Mounting…" : "Mount this drive"
            color: wiz.foreground
            font.family: wiz.fontFamily
            font.pixelSize: Style.font.body
          }
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            enabled: !wiz.service.netMounting
            onClicked: wiz.mapFromBrowse()
          }
        }
      }
    }

    // ---- manual mode ----
    Column {
      visible: wiz.mode === "manual"
      width: parent.width
      spacing: Style.space(6)

      Row {
        spacing: Style.space(4)
        Repeater {
          model: wiz.schemes
          Rectangle {
            id: schemeChip
            required property string modelData
            required property int index
            readonly property bool active: wiz.manualSchemeIndex === schemeChip.index
            width: chipLabel.implicitWidth + Style.space(16)
            height: Style.space(26)
            radius: height / 2
            color: active ? Qt.alpha(wiz.foreground, 0.16) : Qt.alpha(wiz.foreground, 0.05)
            Text {
              id: chipLabel
              anchors.centerIn: parent
              text: (wiz.schemeGlyphs[modelData] || "") + " " + wiz.schemeLabels[modelData]
              color: schemeChip.active ? wiz.foreground : wiz.dim
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.caption
            }
            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: wiz.manualSchemeIndex = schemeChip.index }
          }
        }
      }

      TextField {
        id: manualServer
        width: parent.width
        placeholderText: "Server (e.g. nas.local or 192.168.1.50)"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      Row {
        width: parent.width
        spacing: Style.space(6)
        TextField {
          id: manualShare
          width: parent.width - manualPort.width - Style.space(6)
          placeholderText: "Share or path (optional)"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
          background: Rectangle { radius: Style.cornerRadius
                                  color: Qt.alpha(wiz.foreground, 0.06) }
        }
        TextField {
          id: manualPort
          width: Style.space(64)
          placeholderText: "Port"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
          background: Rectangle { radius: Style.cornerRadius
                                  color: Qt.alpha(wiz.foreground, 0.06) }
        }
      }
      TextField {
        id: manualUser
        width: parent.width
        placeholderText: "User (optional)"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      TextField {
        id: manualPass
        width: parent.width
        echoMode: TextInput.Password
        placeholderText: "Password (optional)"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      CursorSurface {
        width: parent.width
        foreground: wiz.foreground
        fill: Qt.rgba(1, 1, 1, 0.08)
        radius: Style.cornerRadius
        implicitHeight: mmapLabel.implicitHeight + Style.space(12)
        Text {
          id: mmapLabel
          anchors.centerIn: parent
          text: wiz.service.netMounting ? "Mounting…" : "Mount this drive"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
        }
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          enabled: !wiz.service.netMounting && manualServer.text.trim() !== ""
          onClicked: wiz.mapFromManual()
        }
      }
    }

    Text {
      visible: wiz.service.netError !== ""
      width: parent.width
      wrapMode: Text.WordWrap
      text: wiz.service.netError
      color: wiz.urgent
      font.family: wiz.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}

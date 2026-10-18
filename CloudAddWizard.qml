import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model

// gdeyoung.driveway cloud add wizard — pick a provider, sign in (OAuth opens
// the browser for Google/OneDrive/Dropbox; Nextcloud/WebDAV/SFTP/FTP take a
// login), and the remote lands on a supervised systemd unit, then in the tab.
Rectangle {
  id: wiz
  property color foreground: Color.foreground
  property color urgent: Color.urgent
  property string fontFamily: Style.font.family
  property var service: null            // the Service instance (drv)
  signal closed()

  color: "transparent"
  radius: Style.cornerRadius
  readonly property real contentHeight: cwCol.implicitHeight

  readonly property color dim: Qt.darker(foreground, 1.55)

  // key, label, glyph, oauth — static fallback; the live list comes from
  // `driveway cloud providers` via Service.cloudProviders (same keys).
  readonly property var staticProviders: [
    { key: "gdrive",    label: "Google Drive", glyph: "󰊞", oauth: true },
    { key: "onedrive",  label: "OneDrive",     glyph: "󰅠", oauth: true },
    { key: "dropbox",   label: "Dropbox",      glyph: "󰥫", oauth: true },
    { key: "box",       label: "Box",          glyph: "󰒄", oauth: true },
    { key: "pcloud",    label: "pCloud",       glyph: "󰢹", oauth: true },
    { key: "nextcloud", label: "Nextcloud",    glyph: "󰅗", oauth: false },
    { key: "webdav",    label: "WebDAV",       glyph: "󰕮", oauth: false },
    { key: "sftp",      label: "SFTP host",    glyph: "󰣀", oauth: false },
    { key: "ftp",       label: "FTP host",     glyph: "󰢑", oauth: false },
    { key: "s3",        label: "S3 / MinIO / R2", glyph: "󰉟", oauth: false }
  ]
  readonly property var providerModel: (service && service.cloudProviders
                                        && service.cloudProviders.length
                                       ? service.cloudProviders
                                       : staticProviders).concat(
    [{ key: "other", label: "Other backend…", glyph: "󰑭", oauth: false }])
  property var provider: null
  readonly property var wstate: service ? service.cloudWizard : { state: "idle" }
  readonly property bool working: wstate.state === "working"

  function pick(p) {
    if (p.key === "other") {
      service.cloudOtherConfig()
      wiz.closed()
      return
    }
    provider = p
    if (!nameField.text || nameField.text === "" ||
        providerModel.some(function(x) { return x.key === nameField.text }))
      nameField.text = p.key
  }

  function chosen() { return provider || { key: "", oauth: false } }

  function add() {
    var extras = {}
    var p = chosen()
    if (p.key === "nextcloud" || p.key === "webdav") {
      extras.url = ncUrl.text.trim()
      extras.user = ncUser.text.trim()
      if (ncPass.text) extras.password = ncPass.text
    } else if (p.key === "sftp" || p.key === "ftp") {
      extras.host = ncUrl.text.trim()
      extras.user = ncUser.text.trim()
      if (ncPass.text) extras.password = ncPass.text
    } else if (p.key === "s3") {
      extras.url = ncUrl.text.trim()
      extras.user = ncUser.text.trim()
      if (ncPass.text) extras.password = ncPass.text
    }
    service.cloudWizardAdd(nameField.text.trim(), extras, p.key)
  }

  Column {
    id: cwCol
    anchors.fill: parent
    spacing: Style.space(8)

    Row {
      width: parent.width
      spacing: Style.space(8)
      Text {
        text: "Add cloud drive"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.heading
        anchors.verticalCenter: parent.verticalCenter
      }
      Item { width: Style.space(8); height: 1; anchors.verticalCenter: parent.verticalCenter }
      RowButton { glyph: ""; foreground: wiz.foreground; fontFamily: wiz.fontFamily
                  tooltip: "Close"; onActivated: {
                    wiz.service.cloudWizardCancel()
                    wiz.closed()
                  } }
    }

    // provider grid
    GridLayout {
      visible: !wiz.working && wiz.wstate.state !== "done"
      width: parent.width
      columns: 2
      columnSpacing: Style.space(6)
      rowSpacing: Style.space(6)

      Repeater {
        model: wiz.providerModel
        Rectangle {
          required property var modelData
          readonly property bool active: wiz.provider && wiz.provider.key === modelData.key
          readonly property string glyph: modelData.glyph || "󰉉"
          Layout.fillWidth: true
          implicitHeight: Style.space(40)
          radius: Style.cornerRadius
          color: active ? Qt.alpha(wiz.foreground, 0.16)
                        : (pm.containsMouse ? Qt.alpha(wiz.foreground, 0.10)
                                            : Qt.rgba(1, 1, 1, 0.04))
          Row {
            anchors.centerIn: parent
            spacing: Style.space(8)
            Text {
              text: glyph
              color: wiz.foreground
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
            }
            Text {
              text: modelData.label
              color: active ? wiz.foreground : wiz.dim
              font.family: wiz.fontFamily
              font.pixelSize: Style.font.body
              anchors.verticalCenter: parent.verticalCenter
            }
          }
          MouseArea { id: pm; anchors.fill: parent; hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: wiz.pick(modelData) }
        }
      }
    }

    // per-provider fields
    Column {
      visible: !!wiz.provider && !wiz.working && wiz.wstate.state !== "done"
      width: parent.width
      spacing: Style.space(6)
      opacity: 0 + (wiz.provider ? 1 : 0)

      TextField {
        id: nameField
        width: parent.width
        placeholderText: "Remote name (lowercase, for the unit + ~/Cloud folder)"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      TextField {
        id: ncUrl
        visible: wiz.provider && ["nextcloud", "webdav", "sftp", "ftp", "s3"].indexOf(wiz.provider.key) >= 0
        width: parent.width
        placeholderText: wiz.provider && wiz.provider.key === "s3"
          ? "Endpoint (http://host:9000 — leave blank for AWS)"
          : wiz.provider && (wiz.provider.key === "sftp" || wiz.provider.key === "ftp")
          ? "Host (e.g. files.example.com)"
          : "Server URL (https://cloud.example.com/remote.php/dav/)"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      TextField {
        id: ncUser
        visible: wiz.provider && ["nextcloud", "webdav", "sftp", "ftp", "s3"].indexOf(wiz.provider.key) >= 0
        width: parent.width
        placeholderText: wiz.provider && wiz.provider.key === "s3"
          ? "Access key ID" : "User name"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }
      TextField {
        id: ncPass
        visible: wiz.provider && ["nextcloud", "webdav", "sftp", "ftp", "s3"].indexOf(wiz.provider.key) >= 0
        width: parent.width
        echoMode: TextInput.Password
        placeholderText: wiz.provider && wiz.provider.key === "s3"
          ? "Secret access key" : "Password"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(wiz.foreground, 0.06) }
      }

      Text {
        visible: wiz.provider && wiz.provider.oauth
        width: parent.width
        wrapMode: Text.WordWrap
        text: "Your browser opens; sign in and allow access. Come back here."
        color: wiz.dim
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.caption
      }

      CursorSurface {
        width: parent.width
        enabled: !!wiz.provider && nameField.text.trim() !== ""
        foreground: wiz.foreground
        fill: Qt.rgba(1, 1, 1, 0.08)
        radius: Style.cornerRadius
        implicitHeight: addLabel.implicitHeight + Style.space(12)
        opacity: enabled ? 1 : 0.4
        Text {
          id: addLabel
          anchors.centerIn: parent
          text: wiz.provider && wiz.provider.oauth
            ? "Open browser & sign in"
            : "Add drive"
          color: wiz.foreground
          font.family: wiz.fontFamily
          font.pixelSize: Style.font.body
        }
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          enabled: parent.enabled
          onClicked: wiz.add()
        }
      }
    }

    // working / done / error states
    Column {
      visible: wiz.working || wiz.wstate.state === "done" || wiz.wstate.state === "error"
      width: parent.width
      spacing: Style.space(8)

      BusyIndicator {
        visible: wiz.working
        running: visible
        width: Style.space(28); height: Style.space(28)
        anchors.horizontalCenter: parent.horizontalCenter
      }
      Text {
        visible: wiz.working
        width: parent.width
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        text: wiz.wstate.phase || "working…"
        color: wiz.dim
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        visible: wiz.wstate.state === "done"
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "✓ Added — check the Cloud tab"
        color: wiz.foreground
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.body
      }
      Text {
        visible: wiz.wstate.state === "error"
        width: parent.width
        wrapMode: Text.WordWrap
        text: wiz.wstate.error || "failed"
        color: wiz.urgent
        font.family: wiz.fontFamily
        font.pixelSize: Style.font.caption
      }
      RowButton {
        visible: wiz.wstate.state === "done" || wiz.wstate.state === "error"
        label: wiz.wstate.state === "done" ? "Done" : "Back"
        foreground: wiz.foreground; fontFamily: wiz.fontFamily
        onActivated: {
          wiz.service.cloudWizardCancel()
          if (wiz.wstate.state === "done") wiz.closed()
        }
      }
    }
  }
}

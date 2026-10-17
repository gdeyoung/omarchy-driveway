import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

// gdeyoung.driveway panel — every drive in one place, tabbed so depth never
// becomes clutter (house tab pattern from gdeyoung.tailfin).
//   drives   : the OG Mac volume menu — System row, local disks, network
//              shares, cloud mounts; search, mount/eject/open/terminal
//   cloud    : rclone remotes on supervised systemd units; mount/unmount,
//              health, pending uploads, add via rclone config
//   network  : live SMB/NFS/sshfs mounts (persistence lands in v0.2)
Panel {
  id: root
  moduleName: "gdeyoung.driveway"
  ipcTarget: "gdeyoung.driveway"
  manageIpc: false

  property string tab: "drives"
  property string query: ""
  property bool searchFocus: false
  property var infoOpen: ({})   // drive.key -> true
  property bool netWizardOpen: false
  property bool cloudWizardOpen: false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family
  readonly property var tabList: ["drives", "cloud", "network"]
  readonly property var filteredDrives: Model.filterDrives(drv.drives, query)
  readonly property var barState: drv.barState

  function tabTitle(key) {
    if (key === "drives") return "Drives"
    if (key === "cloud") return "Cloud"
    return "Network"
  }

  function setTab(name) {
    tab = name
    searchFocus = false
    Qt.callLater(function() { if (panelFlick) panelFlick.contentY = 0 })
  }

  function switchTab(delta) {
    var index = tabList.indexOf(tab)
    if (index === -1) index = 0
    index = (index + delta + tabList.length) % tabList.length
    setTab(tabList[index])
  }

  function toggleInfo(d) {
    var next = Object.assign({}, root.infoOpen)
    if (next[d.key]) delete next[d.key]
    else next[d.key] = true
    root.infoOpen = next
  }

  Service {
    id: drv
    settings: root.settings
    panelOpen: root.opened
  }

  // Fast poll while open is Service's own timer (panelOpen); refresh on open.
  onOpenedChanged: if (opened) {
    query = ""
    drv.refresh()
    Qt.callLater(function() { if (keyCatcher) keyCatcher.forceActiveFocus() })
  }

  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): string { drv.refresh(); return "ok" }
    function tab(name: string): string { root.setTab(name); return "ok" }
    function cloudmount(name: string): string { drv.cloudMount(name); return "ok" }
    function cloudunmount(name: string): string { drv.cloudUnmount(name); return "ok" }
    function status(): string {
      return JSON.stringify({
        tab: root.tab,
        opened: root.opened,
        drives: drv.drives.length,
        cloud: drv.cloudDrives.length,
        rclone: drv.cloud.rclone,
        unit: drv.cloud.unit,
        network: drv.networkDrives.length,
        barUrgent: root.barState.urgent,
        barBadge: root.barState.badge,
        query: root.query
      })
    }
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // ---- bar icon -----------------------------------------------------------

  readonly property color barIconColor: barState.urgent
    ? (bar ? bar.urgent : Color.urgent)
    : (barState.dim ? Qt.darker(barForeground, 1.55) : barForeground)

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Item {
        Text {
          anchors.centerIn: parent
          text: "󰇅"
          color: root.barIconColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.iconLarge
        }
        Text {
          visible: root.barState.badge > 1
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          text: String(root.barState.badge)
          color: root.barIconColor
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption * 0.7
        }
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton) drv.refresh()
      else if (buttonCode === Qt.MiddleButton) root.setTab("drives")
      else root.toggle()
    }
  }

  // ---- panel --------------------------------------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(560))
    // One source of truth: the scroller holds either tab content or a
    // wizard; fittedContentHeight clamps to available screen space.
    contentHeight: panel.fittedContentHeight(panelFlick.contentHeight, Style.space(760))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) { if (dx !== 0) root.switchTab(dx) }
      onActivateRequested: root.close()
      onCloseRequested: root.close()
      onTextKey: function(t) {
        if (root.searchFocus) return   // typing goes to the search box
        if (t === "1") root.setTab("drives")
        else if (t === "2") root.setTab("cloud")
        else if (t === "3") root.setTab("network")
        else if (t === "/") root.searchFocus = true
        else if (t === "r" || t === "R") drv.refresh()
      }
    }

    Flickable {
      id: panelFlick
      anchors.fill: parent
      contentWidth: width
      contentHeight: root.netWizardOpen || root.cloudWizardOpen
        ? wizHost.implicitHeight
        : column.implicitHeight
      clip: true
      boundsBehavior: Flickable.StopAtBounds
      flickableDirection: Flickable.VerticalFlick
      interactive: contentHeight > height
      ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; interactive: false }

      Column {
        id: column
        visible: !root.netWizardOpen && !root.cloudWizardOpen
        width: panelFlick.width
        spacing: Style.space(12)

        Row {
          spacing: Style.space(6)
          Repeater {
            model: root.tabList
            TabButton {
              required property string modelData
              key: modelData
              label: root.tabTitle(modelData)
            }
          }
        }

        // ================= DRIVES TAB =====================================
        Column {
          visible: root.tab === "drives"
          width: parent.width
          spacing: Style.space(10)

          // Search
          Rectangle {
            width: parent.width
            height: Style.space(34)
            radius: Style.cornerRadius
            color: Qt.rgba(1, 1, 1, 0.05)
            border.width: root.searchFocus ? 1 : 0
            border.color: root.dim

            Row {
              anchors.fill: parent
              anchors.leftMargin: Style.space(10)
              anchors.rightMargin: Style.space(10)
              spacing: Style.space(8)

              Text {
                text: "󰍉"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                anchors.verticalCenter: parent.verticalCenter
              }

              TextInput {
                id: searchInput
                width: parent.width - Style.space(60)
                anchors.verticalCenter: parent.verticalCenter
                text: root.query
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                clip: true
                activeFocusOnPress: true
                onTextEdited: root.query = text
                onActiveFocusChanged: root.searchFocus = activeFocus
                Keys.onEscapePressed: {
                  if (text !== "") text = ""
                  else { root.searchFocus = false; keyCatcher.forceActiveFocus() }
                }
              }

              Text {
                visible: root.query !== ""
                text: "󰅖"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                anchors.verticalCenter: parent.verticalCenter

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: { searchInput.text = ""; root.query = "" }
                }
              }
            }
          }

          Repeater {
            model: root.filteredDrives
            DriveRow {
              required property var modelData
              width: parent.width
              drive: modelData
              busyResult: drv.busyFor(modelData)
              showInfo: !!root.infoOpen[modelData.key]
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              fullWarnPct: drv.fullWarnPct
              onOpenRequested: drv.open(modelData)
              onTerminalRequested: drv.openTerminal(modelData)
              onEjectRequested: function(kill, force) { drv.eject(modelData, kill, force); if (kill) drv.clearBusy(modelData) }
              onMountRequested: drv.mount(modelData, true, false)
              onUnlockRequested: drv.unlock(modelData)
              onInfoToggled: root.toggleInfo(modelData)
            }
          }

          Text {
            visible: root.filteredDrives.length === 0
            width: parent.width
            text: root.query !== "" ? "No drives match “" + root.query + "”." : "No drives. Plug one in — it shows up here."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }
        }

        // ================= CLOUD TAB ======================================
        Column {
          visible: root.tab === "cloud"
          width: parent.width
          spacing: Style.space(10)

          Column {
            visible: !drv.cloud.rclone
            width: parent.width
            spacing: Style.space(8)

            Text {
              width: parent.width
              text: "rclone is not installed — cloud drives need it (and NFS mounts use it too)."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: Text.WordWrap
              horizontalAlignment: Text.AlignHCenter
            }

            CursorSurface {
              width: parent.width
              foreground: root.foreground
              bordered: true
              radius: Style.cornerRadius
              implicitHeight: installLabel.implicitHeight + Style.space(18)

              MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: drv.installRclone()
              }

              Text {
                id: installLabel
                anchors.centerIn: parent
                text: "󰑖  Install rclone now"
                color: root.foreground
                font.family: root.fontFamily
                font.bold: true
                font.pixelSize: Style.font.body
              }
            }

            Text {
              width: parent.width
              text: "A terminal opens and asks for your sudo password:\npacman -S --needed rclone gvfs-nfs"
              color: Qt.darker(root.dim, 1.2)
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              textFormat: Text.PlainText
              horizontalAlignment: Text.AlignHCenter
            }
          }

          Repeater {
            model: drv.cloudDrives
            CloudRow {
              required property var modelData
              width: parent.width
              remote: modelData
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              fullWarnPct: drv.fullWarnPct
              onOpenRequested: if (modelData.mountpoint) drv.run(["xdg-open", modelData.mountpoint])
              onToggleMount: modelData.state === "mounted" || modelData.state === "external"
                ? drv.cloudUnmount(modelData.name)
                : drv.cloudMount(modelData.name)
            }
          }

          Text {
            visible: drv.cloud.rclone && drv.cloudDrives.length === 0
            width: parent.width
            text: "No rclone remotes yet."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          CursorSurface {
            width: parent.width
            foreground: root.foreground
            fill: Qt.rgba(1, 1, 1, 0.04)
            radius: Style.cornerRadius
            implicitHeight: addLabel.implicitHeight + Style.space(16)

            MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.cloudWizardOpen = true
            }

            Text {
            id: addLabel
            anchors.centerIn: parent
            text: "󰐗  Add cloud drive"
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            }
          }
        }

        // ================= NETWORK TAB ====================================
        Column {
          visible: root.tab === "network"
          width: parent.width
          spacing: Style.space(10)

          Repeater {
            // lister covers kernel cifs/nfs/sshfs; gvfs rows come from
            // netMounted below — one row per drive, no duplicates
            model: drv.networkDrives.filter(function(d) {
              return !d.mountpoint || d.mountpoint.indexOf("/gvfs/") < 0
            })
            DriveRow {
              required property var modelData
              width: parent.width
              drive: modelData
              busyResult: drv.busyFor(modelData)
              showInfo: !!root.infoOpen[modelData.key]
              foreground: root.foreground
              urgent: root.urgent
              fontFamily: root.fontFamily
              fullWarnPct: drv.fullWarnPct
              onOpenRequested: drv.open(modelData)
              onTerminalRequested: drv.openTerminal(modelData)
              onEjectRequested: function(kill, force) { drv.eject(modelData, kill, force); if (kill) drv.clearBusy(modelData) }
              onMountRequested: drv.mount(modelData, true, false)
              onUnlockRequested: drv.unlock(modelData)
              onInfoToggled: root.toggleInfo(modelData)
            }
          }

          Text {
            visible: drv.networkDrives.length === 0 && drv.netMounted.length === 0
            width: parent.width
            text: "No network shares mounted."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
          }

          Repeater {
            model: drv.netMounted
            NetMapRow {
              required property var modelData
              width: parent.width
              label: modelData.label
              sublabel: modelData.scheme.toUpperCase() + " · mapped · remounts at login"
              glyph: Model.netGlyph(modelData.scheme)
              mounted: true
              foreground: root.foreground
              fontFamily: root.fontFamily
              onOpenRequested: drv.run(["xdg-open", modelData.path])
              onUnmountRequested: drv.netUnmount(modelData.url)
            }
          }

          Repeater {
            model: drv.netMaps.filter(function(m) {
              return !drv.netMounted.some(function(x) { return x.url === m.url })
            })
            NetMapRow {
              required property var modelData
              width: parent.width
              label: modelData.label
              sublabel: modelData.scheme.toUpperCase() + " · saved map · not mounted"
              glyph: Model.netGlyph(modelData.scheme)
              mounted: false
              foreground: root.foreground
              fontFamily: root.fontFamily
              onMountRequested: drv.netMap({ scheme: modelData.scheme,
                                             server: modelData.server,
                                             share: modelData.share,
                                             port: modelData.port,
                                             path: modelData.path, save: true })
              onForgetRequested: drv.netForget(modelData.id)
            }
          }

          CursorSurface {
            width: parent.width
            foreground: root.foreground
            fill: Qt.rgba(1, 1, 1, 0.04)
            radius: Style.cornerRadius
            implicitHeight: mapDriveLabel.implicitHeight + Style.space(16)

            MouseArea {
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: { root.netWizardOpen = true; netWiz.open() }
            }

            Text {
              id: mapDriveLabel
              anchors.centerIn: parent
              text: "󰅮  Map network drive"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }
          }

          Text {
            width: parent.width
            visible: true
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: "Browse the LAN (Samba, SSH, FTP, NFS, WebDAV) or paste an address. Mapped drives remount at login; credentials are stored encrypted."
            color: Qt.darker(root.dim, 1.2)
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignHCenter
          }
        }
      }

      // wizards — inline as the scroller's content while open (tab column
      // hides above); the panel grows to fit and nothing underdraws
      Column {
        id: wizHost
        visible: root.netWizardOpen || root.cloudWizardOpen
        width: panelFlick.width
        spacing: Style.space(4)

        NetMapWizard {
          id: netWiz
          visible: root.netWizardOpen
          width: parent.width
          height: contentHeight
          foreground: root.foreground
          urgent: root.urgent
          fontFamily: root.fontFamily
          service: drv
          onClosed: root.netWizardOpen = false
        }

        CloudAddWizard {
          id: cloudWiz
          visible: root.cloudWizardOpen
          width: parent.width
          height: contentHeight
          foreground: root.foreground
          urgent: root.urgent
          fontFamily: root.fontFamily
          service: drv
          onClosed: root.cloudWizardOpen = false
        }
      }
    }
  }

  Connections {
    target: drv
    function onNetNeedsCreds(server) {
      root.netWizardOpen = true
      netWiz.openCredsFor(server)
    }
  }

  // ================= components ============================================

  component NetMapRow: CursorSurface {
    id: nrow
    property string label: ""
    property string sublabel: ""
    property string glyph: "󰲂"
    property bool mounted: false
    property color foreground: Color.foreground
    property string fontFamily: Style.font.family
    signal openRequested()
    signal unmountRequested()
    signal mountRequested()
    signal forgetRequested()

    readonly property color dim: Qt.darker(foreground, 1.55)

    fill: Qt.rgba(1, 1, 1, 0.04)
    radius: Style.cornerRadius
    implicitHeight: Style.space(44)

    Row {
      anchors.fill: parent
      anchors.leftMargin: Style.space(10)
      anchors.rightMargin: Style.space(6)
      spacing: Style.space(10)

      Text {
        text: nrow.glyph
        color: nrow.mounted ? nrow.foreground : nrow.dim
        font.family: nrow.fontFamily
        font.pixelSize: Style.font.heading
        anchors.verticalCenter: parent.verticalCenter
      }

      Column {
        width: parent.width - Style.space(50) - actionsN.implicitWidth
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)
        Text {
          width: parent.width
          text: nrow.label
          color: nrow.foreground
          font.family: nrow.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }
        Text {
          width: parent.width
          text: nrow.sublabel
          color: nrow.dim
          font.family: nrow.fontFamily
          font.pixelSize: Style.font.caption
          elide: Text.ElideRight
        }
      }

      Row {
        id: actionsN
        spacing: Style.space(2)
        anchors.verticalCenter: parent.verticalCenter
        RowButton { glyph: "󰝰"; visible: nrow.mounted
                    foreground: nrow.foreground; fontFamily: nrow.fontFamily
                    tooltip: "Open in files"; onActivated: nrow.openRequested() }
        RowButton { glyph: "󰕁"; visible: !nrow.mounted
                    foreground: nrow.foreground; fontFamily: nrow.fontFamily
                    tooltip: "Mount now"; onActivated: nrow.mountRequested() }
        RowButton { glyph: "󰗞"; visible: nrow.mounted
                    foreground: nrow.foreground; fontFamily: nrow.fontFamily
                    tooltip: "Unmount"; onActivated: nrow.unmountRequested() }
        RowButton { glyph: "󰆑"; visible: !nrow.mounted
                    foreground: nrow.dim; fontFamily: nrow.fontFamily
                    tooltip: "Forget this map"; onActivated: nrow.forgetRequested() }
      }
    }
  }

  component TabButton: Rectangle {
    id: tb
    property string key: ""
    property string label: ""
    readonly property bool active: root.tab === key
    width: tabText.implicitWidth + Style.space(20)
    height: Style.space(24)
    radius: Style.cornerRadius
    color: active ? Qt.rgba(1, 1, 1, 0.10) : "transparent"
    border.width: active ? 1 : 0
    border.color: root.dim

    Text {
      id: tabText
      anchors.centerIn: parent
      text: tb.label
      color: tb.active ? root.foreground : root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: tb.active
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.setTab(tb.key)
    }
  }

  component CloudRow: CursorSurface {
    id: crow
    property var remote: null
    property color foreground: Color.foreground
    property color urgent: Color.urgent
    property string fontFamily: Style.font.family
    property int fullWarnPct: 90
    signal openRequested()
    signal toggleMount()

    readonly property color dim: Qt.darker(foreground, 1.55)
    readonly property bool mounted: remote && (remote.state === "mounted" || remote.state === "external")
    readonly property bool urgentState: remote && Model.cloudUrgent(remote.state)
    readonly property bool busyState: remote && remote.state === "starting"
    readonly property bool full: mounted && remote.size > 0 && remote.pct >= fullWarnPct
    readonly property string chip: remote ? Model.cloudStateLabel(remote.state) : ""

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
          text: remote ? (Model.DEFAULT_ICONS[remote.kind] || Model.DEFAULT_ICONS.cloud) : ""
          color: crow.mounted ? crow.foreground : crow.dim
          font.family: crow.fontFamily
          font.pixelSize: Style.font.heading
          anchors.verticalCenter: parent.verticalCenter
        }

        Column {
          width: parent.width - Style.space(60) - actions.implicitWidth
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: remote ? remote.name : ""
            color: crow.foreground
            font.family: crow.fontFamily
            font.pixelSize: Style.font.body
            elide: Text.ElideRight
          }

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: remote ? [remote.type, Model.usageText(remote)].filter(function(s) { return !!s }).join(" · ") : ""
            color: crow.dim
            font.family: crow.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }

          Rectangle {
            width: parent.width
            height: Style.space(4)
            radius: height / 2
            visible: crow.mounted && remote && remote.size > 0
            color: Qt.alpha(crow.dim, 0.35)

            Rectangle {
              width: parent.width * Math.min(1, (remote ? remote.pct : 0) / 100)
              height: parent.height
              radius: parent.radius
              color: crow.full ? crow.urgent : Qt.alpha(crow.foreground, 0.75)
            }
          }
        }

        Row {
          id: actions
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(6)

          Text {
            visible: crow.remote && crow.remote.pending > 0
            text: crow.remote ? ("󰅃 " + crow.remote.pending) : ""
            color: crow.urgent
            font.family: crow.fontFamily
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }

          // State chip
          Rectangle {
            width: chipText.implicitWidth + Style.space(12)
            height: Style.space(20)
            radius: height / 2
            color: crow.urgentState ? Qt.alpha(crow.urgent, 0.18)
                 : crow.mounted ? Qt.alpha(crow.foreground, 0.12)
                 : Qt.rgba(1, 1, 1, 0.05)
            anchors.verticalCenter: parent.verticalCenter

            Text {
              id: chipText
              anchors.centerIn: parent
              text: crow.chip
              color: crow.urgentState ? crow.urgent : (crow.mounted ? crow.foreground : crow.dim)
              font.family: crow.fontFamily
              font.pixelSize: Style.font.caption
            }
          }

          RowButton {
            visible: crow.mounted && crow.remote && crow.remote.mountpoint !== ""
            glyph: "󰝰"
            tooltip: "Open in file manager"
            fontFamily: crow.fontFamily
            foreground: crow.foreground
            onActivated: crow.openRequested()
          }

          RowButton {
            visible: !crow.busyState
            label: crow.mounted ? "Unmount" : "Mount"
            fontFamily: crow.fontFamily
            foreground: crow.foreground
            onActivated: crow.toggleMount()
          }
        }
      }
    }
  }
}

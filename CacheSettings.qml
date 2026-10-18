import QtQuick
import QtQuick.Controls
import qs.Commons
import qs.Ui

// Disk-cache limits: one global default + per-remote overrides.  Inline view
// (replaces tab content, same contract as the wizards: height = contentHeight,
// closed() returns to the tab column).
Column {
  id: cache

  property color foreground: "#fff"
  property color urgent: "#f66"
  property string fontFamily: "sans"
  property var service: null
  signal closed()

  // service.cloudCache = {global, globalIsCustom, remotes:{name:{limit,isOverride}}}
  readonly property var info: service ? service.cloudCache : ({})
  readonly property var remoteNames: {
    var r = info && info.remotes ? info.remotes : {}
    var names = []
    for (var k in r) names.push(k)
    names.sort()
    return names
  }

  width: parent ? parent.width : 0
  spacing: Style.space(10)

  Text {
    width: parent.width
    text: "Disk cache limits"
    color: cache.foreground
    font.family: cache.fontFamily
    font.pixelSize: Style.font.subTitle
    font.weight: Font.Bold
  }

  Text {
    width: parent.width
    wrapMode: Text.Wrap
    color: Qt.alpha(cache.foreground, 0.7)
    font.family: cache.fontFamily
    font.pixelSize: Style.font.caption
    text: "Cached Drive files live on this laptop so reopens are instant. " +
          "Older files are evicted automatically above the limit. " +
          "\u201Coff\u201D means no limit — the cache can then grow until the " +
          "disk is full."
  }

  // ── global default ────────────────────────────────────────────────
  Row {
    width: parent.width
    spacing: Style.space(8)

    Text {
      id: gLabel
      text: "Default for all drives"
      color: cache.foreground
      font.family: cache.fontFamily
      font.pixelSize: Style.font.body
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - gField.width - gSave.width - parent.spacing * 2
      elide: Text.ElideRight
    }

    TextField {
      id: gField
      width: Style.space(90)
      text: cache.info && cache.info.global ? cache.info.global : ""
      placeholderText: "10G"
      color: cache.foreground
      font.family: cache.fontFamily
      font.pixelSize: Style.font.body
      horizontalAlignment: TextInput.AlignHCenter
      background: Rectangle { radius: Style.cornerRadius
                              color: Qt.alpha(cache.foreground, 0.06) }
      onAccepted: gSave.clicked(null)
      Component.onCompleted: forceActiveFocus()
    }

    CursorSurface {
      id: gSave
      foreground: cache.foreground
      bordered: true
      radius: Style.cornerRadius
      implicitHeight: gField.implicitHeight
      width: gSaveText.implicitWidth + Style.space(20)

      MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: function() {
          service.cloudCacheSet("global", gField.text)
        }
      }
      Text {
        id: gSaveText
        anchors.centerIn: parent
        text: service && service.cloudCacheBusy === "global" ? "…" : "Save"
        color: cache.foreground
        font.family: cache.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }

  // ── per-remote rows ───────────────────────────────────────────────
  Repeater {
    model: cache.remoteNames

    delegate: Row {
      width: cache.width
      spacing: Style.space(8)

      required property string modelData
      readonly property var rinfo: cache.info.remotes[modelData]
      readonly property bool isOverride: rinfo ? rinfo.isOverride : false

      Text {
        text: modelData + (parent.isOverride ? "  (own limit)" : "")
        color: cache.foreground
        font.family: cache.fontFamily
        font.pixelSize: Style.font.body
        font.weight: parent.isOverride ? Font.Bold : Font.Normal
        anchors.verticalCenter: parent.verticalCenter
        width: parent.width - rField.width - rSave.width - rUse.width
                - parent.spacing * 3
        elide: Text.ElideRight
      }

      TextField {
        id: rField
        width: Style.space(90)
        text: parent.rinfo && parent.rinfo.limit ? parent.rinfo.limit : ""
        placeholderText: cache.info ? cache.info.global : "10G"
        color: cache.foreground
        font.family: cache.fontFamily
        font.pixelSize: Style.font.body
        horizontalAlignment: TextInput.AlignHCenter
        background: Rectangle { radius: Style.cornerRadius
                                color: Qt.alpha(cache.foreground, 0.06) }
        onAccepted: rSave.clicked(null)
      }

      CursorSurface {
        id: rSave
        foreground: cache.foreground
        bordered: true
        radius: Style.cornerRadius
        implicitHeight: rField.implicitHeight
        width: rSaveText.implicitWidth + Style.space(20)

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: function() {
            service.cloudCacheSet(modelData, rField.text)
          }
        }
        Text {
          id: rSaveText
          anchors.centerIn: parent
          text: service && service.cloudCacheBusy === modelData ? "…" : "Set"
          color: cache.foreground
          font.family: cache.fontFamily
          font.pixelSize: Style.font.caption
        }
      }

      CursorSurface {
        id: rUse
        visible: parent.isOverride
        foreground: cache.foreground
        radius: Style.cornerRadius
        implicitHeight: rField.implicitHeight
        width: rUseText.implicitWidth + Style.space(16)

        MouseArea {
          anchors.fill: parent
          hoverEnabled: true
          cursorShape: Qt.PointingHandCursor
          onClicked: function() {
            // sending the global value clears the override server-side
            service.cloudCacheSet(modelData, cache.info.global)
          }
        }
        Text {
          id: rUseText
          anchors.centerIn: parent
          text: "use default"
          color: Qt.alpha(cache.foreground, 0.7)
          font.family: cache.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // ── back ──────────────────────────────────────────────────────────
  CursorSurface {
    width: parent.width
    foreground: cache.foreground
    bordered: true
    radius: Style.cornerRadius
    implicitHeight: backLabel.implicitHeight + Style.space(12)

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: cache.closed()
    }
    Text {
      id: backLabel
      anchors.centerIn: parent
      text: "󰅁  Back to cloud drives"
      color: cache.foreground
      font.family: cache.fontFamily
      font.pixelSize: Style.font.caption
    }
  }
}

import QtQuick
import qs.Commons
import qs.Ui

// Glyph or text button with tooltip; fires activated on click.
Item {
  id: btn
  property string glyph: ""
  property string label: ""
  property string tooltip: ""
  property string fontFamily: Style.font.family
  property color foreground: Color.foreground
  signal activated()

  readonly property bool hasGlyph: glyph !== ""
  implicitWidth: hasGlyph ? Style.space(26) : textLabel.implicitWidth + Style.space(16)
  implicitHeight: Style.space(26)

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: mouse.containsMouse ? Qt.alpha(btn.foreground, 0.12) : "transparent"
  }

  Text {
    id: textLabel
    anchors.centerIn: parent
    text: btn.hasGlyph ? btn.glyph : btn.label
    color: btn.foreground
    font.family: btn.fontFamily
    font.pixelSize: btn.hasGlyph ? Style.font.body : Style.font.caption
  }

  MouseArea {
    id: mouse
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    onClicked: btn.activated()
  }

  PanelToolTip {
    visible: mouse.containsMouse && btn.tooltip !== ""
    text: btn.tooltip
    fontFamily: btn.fontFamily
  }
}

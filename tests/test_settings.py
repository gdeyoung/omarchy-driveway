"""In-panel general settings (v0.4.2): wiring pins.

Omarchy renders no UI from the manifest schema, so settings ship as an
in-panel view (GeneralSettings.qml) persisted through the plugin-shell
updateEntryInline API (serialized + confirmed writes, powercore pattern).
These tests pin the WIRING: the keys the view writes, the Service functions
it delegates to, the Panel gating that swaps it in, and the shell-API call
that persists. A comment or a renamed function must fail here.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def qml(name: str) -> str:
    return (ROOT / name).read_text()


class SettingsViewWiring(unittest.TestCase):
    def setUp(self):
        self.view = qml("GeneralSettings.qml")
        self.service = qml("Service.qml")
        self.panel = qml("Panel.qml")

    def test_view_exists_with_house_contract(self):
        self.assertIn("signal closed()", self.view)
        self.assertIn("property var service: null", self.view)
        # height contract: parent sizes from implicitHeight (inline-view pattern)
        self.assertIn("spacing: Style.space", self.view)

    def test_view_writes_exactly_the_four_user_keys(self):
        written = [
            line.strip()
            for line in self.view.splitlines()
            if "saveSetting(" in line and "function" not in line
        ]
        joined = "\n".join(written)
        for key in ("pollIntervalSec", "fullWarnPct"):
            self.assertIn('"%s"' % key, joined)
        # toggles ride the Repeater model keys
        for key in ("showNetwork", "showUnmounted"):
            self.assertIn('key: "%s"' % key, self.view)

    def test_service_defines_persistence_machinery(self):
        for needle in (
            "function saveSetting(key, value)",
            "function drainSettings()",
            "property var shellApi: null",
            "property var confirmedSettings: ({})",
            "property var pendingSettingPatches: ([])",
            "property bool settingsWriteBusy: false",
            "id: settingsBusyTimer",
            'shellApi.updateEntryInline("gdeyoung.driveway", merged)',
            "onSettingsChanged: confirmedSettings = settings || ({})",
        ):
            self.assertIn(needle, self.service)

    def test_service_exposes_read_helpers_the_view_binds(self):
        self.assertIn("readonly property int pollSec:", self.service)
        self.assertIn("function settingBool(name)", self.service)

    def test_panel_binds_shell_api_and_gates_the_view(self):
        self.assertIn(
            "shellApi: root.bar ? (root.bar.shell || null) : null", self.panel
        )
        self.assertIn("property bool settingsOpen: false", self.panel)
        # all three gating spots: contentHeight, tab column hidden, wiz host
        self.assertEqual(self.panel.count("root.settingsOpen"), 6)
        self.assertIn("onClosed: root.settingsOpen = false", self.panel)

    def test_panel_gear_opens_settings_and_closes_siblings(self):
        self.assertIn("󰒓", self.panel)
        i = self.panel.index("root.settingsOpen = true")
        gear = self.panel[max(0, i - 400) : i + 100]
        for needle in (
            "root.netWizardOpen = false",
            "root.cacheOpen = false",
            "root.settingsOpen = true",
        ):
            self.assertIn(needle, gear)

    def test_footer_shortcut_hint(self):
        # last child of the tab column: dim caption mirroring README Keyboard
        i = self.panel.index("1·2·3 tabs")
        block = self.panel[max(0, i - 300) : i + 250]
        for needle in (
            "keyboard affordance",
            "Style.font.caption",
            "Text.AlignHCenter",
        ):
            self.assertIn(needle, block)

    def test_manifest_schema_matches_view_keys_and_defaults(self):
        schema = json.loads((ROOT / "manifest.json").read_text())["barWidget"]["schema"]
        by_key = {e["key"]: e for e in schema}
        self.assertEqual(by_key["pollIntervalSec"]["defaultValue"], 10)
        self.assertEqual(by_key["fullWarnPct"]["defaultValue"], 90)
        self.assertIs(by_key["showNetwork"]["defaultValue"], True)
        self.assertIs(by_key["showUnmounted"]["defaultValue"], True)


if __name__ == "__main__":
    unittest.main()

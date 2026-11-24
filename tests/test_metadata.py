import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "packages_esp"


def test_metadata_and_service_descriptions():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["domain"] == "packages_esp"
    assert manifest["config_flow"] and manifest["version"]
    services = yaml.safe_load((INTEGRATION / "services.yaml").read_text())
    assert set(services) == {
        "get_deliveries",
        "get_summary",
        "refresh",
        "mark_delivered",
        "mark_collected",
        "set_expected_date",
        "ignore",
        "snooze",
        "clear_override",
    }
    for language in ("en", "es"):
        translation = json.loads((INTEGRATION / "translations" / f"{language}.json").read_text())
        assert translation["config"]["step"]["imap"]["data"]["password"]
    assert json.loads((ROOT / "hacs.json").read_text())["name"]

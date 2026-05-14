"""CI gate: checked-in openapi.json matches FastAPI's app.openapi() output.

Re-generate with:
    uv run --package unifi-api-server python -c \\
      "from unifi_api.server import create_app; \\
       from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig; \\
       import os, tempfile, json; os.environ['UNIFI_API_DB_KEY'] = 'k'; \\
       td = tempfile.mkdtemp(); \\
       cfg = ApiConfig(http=HttpConfig(host='127.0.0.1', port=8080, cors_origins=()), \\
                       logging=LoggingConfig(level='WARNING'), \\
                       db=DbConfig(path=f'{td}/state.db')); \\
       app = create_app(cfg); \\
       print(json.dumps(app.openapi(), indent=2, sort_keys=True))" \\
      > apps/api/openapi.json
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.server import create_app

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def test_openapi_artifact_matches_app() -> None:
    """The checked-in openapi.json matches the live app.openapi() output."""
    os.environ["UNIFI_API_DB_KEY"] = "k"
    with tempfile.TemporaryDirectory() as td:
        cfg = ApiConfig(
            http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
            logging=LoggingConfig(level="WARNING"),
            db=DbConfig(path=f"{td}/state.db"),
        )
        app = create_app(cfg)
        actual = json.dumps(app.openapi(), indent=2, sort_keys=True).strip()

    expected = SPEC_PATH.read_text(encoding="utf-8").strip()

    assert actual == expected, "openapi.json is stale. Re-export per docstring above."

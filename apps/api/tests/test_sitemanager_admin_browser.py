"""Execute admin browser handlers with synthetic DOM/transport boundaries."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[1] / "src/unifi_api/templates/admin"


def node(source):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node is needed to execute the bundled admin browser handlers")
    result = subprocess.run([executable, "--input-type=module", "-e", source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_csv_download_carries_cloud_filter_and_admin_bearer():
    template = (TEMPLATES / "audit/_filters.html").read_text()
    assert 'onclick="downloadAuditCsv(event)"' in template
    script = re.search(r"<script>(.*?)</script>", template, re.S).group(1)
    node(
        """
import assert from 'node:assert/strict';
let clicked = false, revoked = false, prevented = false;
const link = {click() {clicked = true}, remove() {}};
globalThis.document = {getElementById() {return {}}, createElement() {return link}, body: {appendChild() {}}};
globalThis.FormData = class {
  constructor() {return [['sitemanager_connection', 'synthetic-local-id'], ['outcome', 'success']]}
};
globalThis.localStorage = {getItem() {return 'synthetic-admin-bearer'}};
globalThis.fetch = async (path, options) => {
  const url = new URL(path, 'http://127.0.0.1');
  assert.equal(url.pathname, '/admin/audit/export.csv');
  assert.equal(url.searchParams.get('sitemanager_connection'), 'synthetic-local-id');
  assert.equal(url.searchParams.get('outcome'), 'success');
  assert.equal(options.headers.Authorization, 'Bearer synthetic-admin-bearer');
  assert.equal(options.redirect, 'error');
  return {ok: true, status: 200, blob: async () => ({})};
};
URL.createObjectURL = () => 'blob:synthetic';
URL.revokeObjectURL = value => {assert.equal(value, 'blob:synthetic'); revoked = true};
"""
        + script
        + """
await downloadAuditCsv({preventDefault() {prevented = true}});
assert.equal(link.download, 'audit.csv');
assert.equal(link.href, 'blob:synthetic');
assert.ok(clicked && revoked && prevented);
"""
    )


def test_probe_failure_fragment_is_visible_to_htmx():
    template = (TEMPLATES / "sitemanager/page.html").read_text()
    handler = re.search(r'hx-on::before-swap="([^"]+)"', template).group(1)
    node(
        """
import assert from 'node:assert/strict';
const event = {detail: {xhr: {status: 502}, shouldSwap: false}};
"""
        + handler
        + "\nassert.equal(event.detail.shouldSwap, true);"
    )

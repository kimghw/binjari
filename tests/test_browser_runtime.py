"""Exercise CDP operations and inspect the actual driver protocol traffic."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


def test_cdp_without_runtime_enable():
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if not chrome.exists():
        pytest.skip("System Chrome is required")
    code = r'''
import subprocess
import tempfile
import time
from pathlib import Path
from ktx_watcher.browser import sync_playwright
from ktx_watcher.dom import read_page_state, first_visible
import sys

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
    proc = subprocess.Popen([
        CHROME, '--headless=new', '--remote-debugging-port=0',
        '--user-data-dir=' + profile, '--no-first-run', 'about:blank',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        active = Path(profile) / 'DevToolsActivePort'
        deadline = time.monotonic() + 20
        while not active.exists():
            assert time.monotonic() < deadline, 'Chrome startup timed out'
            time.sleep(0.1)
        port, ws_path = active.read_text().splitlines()[:2]
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp('ws://127.0.0.1:' + port + ws_path)
            context = browser.contexts[0]
            page = context.pages[0]
            page.goto('data:text/html,<input><button onclick="document.title=\'clicked\'">Go</button><iframe srcdoc="<p>frame</p>"></iframe>')
            page.locator('input').fill('test')
            page.locator('button').click()
            assert page.title() == 'clicked'
            assert page.locator('input').input_value() == 'test'
            assert page.frame_locator('iframe').locator('p').inner_text() == 'frame'
            assert page.evaluate('1 + 2') == 3
            page.set_content('<input id="origin" value="Seoul"><input id="dest" value="Busan">'
                             '<div role="dialog" style="display:none">hidden</div>'
                             '<div role="dialog">visible</div><button hidden>OK</button>'
                             '<button onclick="document.title=\'confirmed\'">OK</button>')
            print('BASELINE_START', file=sys.stderr, flush=True)
            origin = page.locator('#origin').input_value()
            dest = page.locator('#dest').input_value()
            body = page.locator('body').inner_text()
            modal = page.locator('[role=dialog]').nth(1).inner_text()
            print('BASELINE_END', file=sys.stderr, flush=True)
            print('BATCH_START', file=sys.stderr, flush=True)
            state = read_page_state(page, inputs={'origin': '#origin', 'dest': '#dest'})
            print('BATCH_END', file=sys.stderr, flush=True)
            assert state['inputs'] == {'origin': origin, 'dest': dest}
            assert state['body'] == body
            assert state['modals'] == [modal]
            first_visible(page, 'button').click()
            assert page.title() == 'confirmed'
            with page.expect_popup() as popup_info:
                page.evaluate("window.open('about:blank')")
            popup = popup_info.value
            popup.set_content('<p>popup</p>')
            assert popup.locator('p').inner_text() == 'popup'
            popup.close()
            page.goto('data:text/html,<button>Go</button>')
            page.reload()
            assert page.locator('button').inner_text() == 'Go'
            from ktx_watcher.korail import client as client_mod
            client_mod.HUMANIZE = False
            client_mod.attach_context_popup_guard(context)
            client_mod.attach_context_popup_guard(context)
            managed = context.new_page()
            assert not managed.is_closed()
            managed.set_content('<input><div role="dialog">-8002'
                                '<button onclick="this.parentElement.remove()">'
                                '\uD655\uC778</button></div>')
            client_mod.human_type(managed.locator('input'), 'batch input')
            assert managed.locator('input').input_value() == 'batch input'
            assert client_mod.dismiss_macro_notice(managed)
            assert not client_mod.dismiss_macro_notice(managed)
            managed.close()
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)
'''
    result = subprocess.run(
        [sys.executable, "-c", "CHROME = " + repr(str(chrome)) + "\n" + code],
        env={**os.environ, "DEBUG": "pw:protocol",
             "REBROWSER_PATCHES_RUNTIME_FIX_MODE": "0"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, result.stderr[-12000:]
    methods = re.findall(r'"method"\s*:\s*"([^"]+)"', result.stderr)
    assert "Runtime.callFunctionOn" in methods, "Protocol logging must be active"
    assert "Runtime.enable" not in methods
    baseline = result.stderr.split('BASELINE_START', 1)[1].split('BASELINE_END', 1)[0]
    batch = result.stderr.split('BATCH_START', 1)[1].split('BATCH_END', 1)[0]
    baseline_calls = baseline.count('SEND ►')
    batch_calls = batch.count('SEND ►')
    assert 0 < batch_calls < baseline_calls, (baseline_calls, batch_calls)
    print(f"DOM protocol commands: {baseline_calls} -> {batch_calls}")

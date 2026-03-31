from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import quote, urlparse


DEFAULT_CDP_PORT = 9222
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_URL = "https://www.perplexity.ai/"
DEFAULT_PROFILE_DIR = Path.home() / ".open-perplexity" / "chrome-profile"

MODEL_KEYWORDS = {
    "gpt": "GPT",
    "chatgpt": "GPT",
    "claude": "Claude Sonnet",
    "claude-opus": "Claude Opus",
    "sonar": "Sonar",
    "gemini": "Gemini",
    "nemotron": "Nemotron",
    "grok": "Grok",
}

JS_SUBMIT = """
(function() {
    var ce = document.querySelector('[contenteditable="true"]');
    if (ce) {
        ce.focus();
        var ev = new KeyboardEvent('keydown', {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true});
        ce.dispatchEvent(ev);
        return 'enter_on_contenteditable';
    }
    var ta = document.querySelector('textarea');
    if (ta) {
        ta.focus();
        var ev = new KeyboardEvent('keydown', {key:'Enter',code:'Enter',keyCode:13,which:13,bubbles:true,cancelable:true});
        ta.dispatchEvent(ev);
        return 'enter_on_textarea';
    }
    var btns = document.querySelectorAll('button');
    for (var b of btns) {
        var label = (b.getAttribute('aria-label') || '').toLowerCase();
        var svg = b.querySelector('svg');
        if (label.includes('submit') || label.includes('send') || label.includes('ask') || svg) {
            b.click();
            return 'clicked:' + (label || 'svg_button');
        }
    }
    return 'no_submit_found';
})()
"""

JS_GET_RESPONSE = """
(function() {
    var blocks = document.querySelectorAll('[class*="prose"], [class*="answer"], [class*="response"], [class*="markdown"]');
    var texts = [];
    for (var b of blocks) {
        var t = b.innerText.trim();
        if (t.length > 20) texts.push(t);
    }
    if (texts.length > 0) return texts.join('\\n---\\n');
    var main = document.querySelector('main') || document.body;
    return main.innerText.substring(0, 50000);
})()
"""

JS_CHECK_LOADING = """
(function() {
    var spinners = document.querySelectorAll('[class*="animate"], [class*="loading"], [class*="typing"], [class*="pulse"]');
    for (var s of spinners) {
        var style = window.getComputedStyle(s);
        if (style.display !== 'none' && style.visibility !== 'hidden' && s.offsetHeight > 0) {
            return true;
        }
    }
    return false;
})()
"""

JS_FOCUS_INPUT = """
(function() {
    var ce = document.querySelector('[contenteditable="true"]');
    if (ce) { ce.focus(); return 'contenteditable'; }
    var ta = document.querySelector('textarea');
    if (ta) { ta.focus(); return 'textarea'; }
    return 'not_found';
})()
"""


class OpenPerplexityError(RuntimeError):
    """Base error raised by this package."""


class SimpleWebSocket:
    """Minimal RFC 6455 websocket client using only the standard library."""

    def __init__(self, url: str, timeout: int = 10) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise OpenPerplexityError(f"Invalid websocket URL: {url}")
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            self.sock = context.wrap_socket(self.sock, server_hostname=host)
        self.sock.settimeout(timeout)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(request.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OpenPerplexityError("WebSocket handshake failed")
            response += chunk
        if b"101" not in response.split(b"\r\n")[0]:
            raise OpenPerplexityError(f"WebSocket upgrade rejected: {response[:200]!r}")

    def send(self, data: str) -> None:
        payload = data.encode("utf-8")
        frame = bytearray([0x81])
        length = len(payload)
        if length < 126:
            frame.append(0x80 | length)
        elif length < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack(">H", length))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack(">Q", length))
        mask = os.urandom(4)
        frame.extend(mask)
        frame.extend(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        self.sock.sendall(frame)

    def recv(self, timeout: float = 30) -> str:
        self.sock.settimeout(timeout)
        header = self._recv_exact(2)
        opcode = header[0] & 0x0F
        masked = bool(header[1] & 0x80)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        if opcode == 0x08:
            raise OpenPerplexityError("WebSocket closed by server")
        if opcode == 0x09:
            self._send_pong(payload)
            return self.recv(timeout)
        return payload.decode("utf-8", errors="replace")

    def _recv_exact(self, size: int) -> bytes:
        data = b""
        while len(data) < size:
            chunk = self.sock.recv(size - len(data))
            if not chunk:
                raise OpenPerplexityError("Connection closed")
            data += chunk
        return data

    def _send_pong(self, payload: bytes) -> None:
        frame = bytearray([0x8A, 0x80 | len(payload)])
        mask = os.urandom(4)
        frame.extend(mask)
        frame.extend(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        self.sock.sendall(frame)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


@dataclass
class RunConfig:
    prompt: str
    model: Optional[str] = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    cdp_port: int = DEFAULT_CDP_PORT
    start_url: str = DEFAULT_URL
    profile_dir: Path = DEFAULT_PROFILE_DIR
    chrome_path: Optional[str] = None
    verbose: bool = False


def log(message: str, *, verbose: bool = True) -> None:
    if verbose:
        print(message, file=sys.stderr)


def cdp_http(port: int, path: str, method: str = "GET") -> Any:
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def is_cdp_reachable(port: int) -> bool:
    try:
        cdp_http(port, "/json/version")
        return True
    except Exception:
        return False


def find_perplexity_tab(port: int) -> Optional[Dict[str, Any]]:
    tabs = cdp_http(port, "/json")
    for tab in tabs:
        if tab.get("type") == "page" and "perplexity" in tab.get("url", "").lower():
            return tab
    return None


def create_new_tab(port: int, url: str) -> Dict[str, Any]:
    return cdp_http(port, f"/json/new?{quote(url, safe='')}", method="PUT")


def cdp_send(
    ws: SimpleWebSocket,
    method: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    msg_id: Optional[int] = None,
) -> int:
    message_id = msg_id if msg_id is not None else int(time.time() * 1000) % 1_000_000
    message: Dict[str, Any] = {"id": message_id, "method": method}
    if params:
        message["params"] = params
    ws.send(json.dumps(message))
    return message_id


def cdp_recv_result(ws: SimpleWebSocket, msg_id: int, *, timeout: float = 30) -> Dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = max(0.5, deadline - time.time())
        try:
            payload = ws.recv(timeout=remaining)
        except socket.timeout:
            continue
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if data.get("id") == msg_id:
            if "error" in data:
                raise OpenPerplexityError(f"CDP error: {data['error']}")
            return data.get("result", {})
    raise TimeoutError(f"CDP response timeout for id={msg_id}")


def cdp_evaluate(ws: SimpleWebSocket, expression: str, *, timeout: float = 30) -> str:
    message_id = cdp_send(
        ws,
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        },
    )
    result = cdp_recv_result(ws, message_id, timeout=timeout)
    value = result.get("result", {})
    if value.get("type") == "string":
        return value.get("value", "")
    return json.dumps(value.get("value", ""), ensure_ascii=False)


def cdp_navigate(ws: SimpleWebSocket, url: str, *, timeout: float = 15) -> None:
    message_id = cdp_send(ws, "Page.navigate", {"url": url})
    cdp_recv_result(ws, message_id, timeout=timeout)
    time.sleep(3)


def detect_chrome_binary() -> Optional[str]:
    env_override = os.environ.get("OPEN_PERPLEXITY_CHROME")
    if env_override:
        return env_override

    candidates = [
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def get_default_profile_source() -> Optional[Path]:
    candidates = [
        Path.home() / ".config" / "google-chrome",
        Path.home() / ".config" / "chromium",
        Path.home() / "Library" / "Application Support" / "Google" / "Chrome",
        Path.home() / "Library" / "Application Support" / "Chromium",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
    ]
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return candidate
    return None


def prepare_profile_dir(profile_dir: Path, *, verbose: bool) -> None:
    source = get_default_profile_source()
    if profile_dir.exists():
        for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "SingletonCookie-journal"):
            lock_path = profile_dir / lock_name
            if lock_path.exists():
                lock_path.unlink()
        return
    if source is None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        return
    log(f"Copying browser profile to {profile_dir} so your Perplexity login can be reused.", verbose=verbose)
    shutil.copytree(source, profile_dir, symlinks=True, ignore_dangling_symlinks=True)
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "SingletonCookie-journal"):
        lock_path = profile_dir / lock_name
        if lock_path.exists():
            lock_path.unlink()


def ensure_chrome_with_cdp(
    port: int,
    *,
    profile_dir: Path,
    chrome_path: Optional[str],
    verbose: bool,
) -> None:
    if is_cdp_reachable(port):
        log(f"Chrome CDP is already reachable on port {port}.", verbose=verbose)
        return

    browser = chrome_path or detect_chrome_binary()
    if not browser:
        raise OpenPerplexityError(
            "Could not find Chrome or Chromium. Install it, or pass --chrome-path / set OPEN_PERPLEXITY_CHROME."
        )

    prepare_profile_dir(profile_dir, verbose=verbose)

    command = [
        browser,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
    ]
    if sys.platform == "darwin":
        command.append("--new-window")

    log(f"Launching Chrome with CDP on port {port}.", verbose=verbose)
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    for attempt in range(20):
        time.sleep(1)
        if is_cdp_reachable(port):
            log(f"Chrome CDP is ready after {attempt + 1} second(s).", verbose=verbose)
            return
    raise OpenPerplexityError("Chrome CDP startup timed out.")


def select_model(ws: SimpleWebSocket, model_name: str, *, verbose: bool) -> bool:
    keyword = MODEL_KEYWORDS.get(model_name.lower())
    if not keyword:
        log(f"Unknown model '{model_name}'. Skipping model selection.", verbose=verbose)
        return False

    js_find_button = """
    (function() {
        var models = ['Model','GPT','Sonar','Claude','Gemini','Nemotron','Grok','Best'];
        var btns = document.querySelectorAll('button');
        for (var btn of btns) {
            var aria = btn.getAttribute('aria-label') || '';
            for (var m of models) {
                if (aria.includes(m)) {
                    var rect = btn.getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        return JSON.stringify({x: rect.x + rect.width/2, y: rect.y + rect.height/2, label: aria});
                    }
                }
            }
        }
        return JSON.stringify({error:'not_found'});
    })()
    """
    button = None
    for _ in range(10):
        button_raw = cdp_evaluate(ws, js_find_button, timeout=5)
        button = json.loads(button_raw)
        if "error" not in button:
            break
        time.sleep(1)
    if button is None or "error" in button:
        log("Model button was not found.", verbose=verbose)
        return False

    for event_type in ("mousePressed", "mouseReleased"):
        message_id = cdp_send(
            ws,
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": button["x"],
                "y": button["y"],
                "button": "left",
                "clickCount": 1,
            },
        )
        cdp_recv_result(ws, message_id, timeout=5)
        time.sleep(0.1)
    time.sleep(1.5)

    js_find_model = """
    (function(keyword) {
        var all = document.querySelectorAll('*');
        for (var el of all) {
            var text = (el.textContent || '').trim();
            if (text.length > 2 && text.length < 60 && el.children.length === 0) {
                var style = window.getComputedStyle(el);
                if (style.display !== 'none' && style.visibility !== 'hidden') {
                    if (text.includes(keyword)) {
                        var rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            return JSON.stringify({x: rect.x + rect.width/2, y: rect.y + rect.height/2, text: text});
                        }
                    }
                }
            }
        }
        return JSON.stringify({error: 'model_not_found'});
    })(%s)
    """ % json.dumps(keyword)
    model_raw = cdp_evaluate(ws, js_find_model, timeout=5)
    model = json.loads(model_raw)
    if "error" in model:
        log(f"Could not find a visible model containing '{keyword}'.", verbose=verbose)
        return False

    log(f"Selecting model: {model['text']}", verbose=verbose)
    for event_type in ("mousePressed", "mouseReleased"):
        message_id = cdp_send(
            ws,
            "Input.dispatchMouseEvent",
            {
                "type": event_type,
                "x": model["x"],
                "y": model["y"],
                "button": "left",
                "clickCount": 1,
            },
        )
        cdp_recv_result(ws, message_id, timeout=5)
        time.sleep(0.1)
    time.sleep(1)
    return True


def run_prompt(config: RunConfig) -> str:
    ensure_chrome_with_cdp(
        config.cdp_port,
        profile_dir=config.profile_dir,
        chrome_path=config.chrome_path,
        verbose=config.verbose,
    )
    tab = find_perplexity_tab(config.cdp_port)
    if tab:
        log(f"Reusing Perplexity tab: {tab['url']}", verbose=config.verbose)
    else:
        log("No Perplexity tab found. Creating a new one.", verbose=config.verbose)
        tab = create_new_tab(config.cdp_port, config.start_url)
        time.sleep(4)

    websocket_url = tab.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise OpenPerplexityError("Could not get the WebSocket debugger URL.")

    ws = SimpleWebSocket(websocket_url, timeout=15)
    try:
        cdp_navigate(ws, config.start_url)
        time.sleep(5)

        if config.model:
            select_model(ws, config.model, verbose=config.verbose)

        input_target = cdp_evaluate(ws, JS_FOCUS_INPUT, timeout=10)
        log(f"Input target: {input_target}", verbose=config.verbose)
        if input_target == "not_found":
            raise OpenPerplexityError("Could not find the Perplexity input box.")

        time.sleep(0.3)
        message_id = cdp_send(ws, "Input.insertText", {"text": config.prompt})
        cdp_recv_result(ws, message_id, timeout=10)

        try:
            down_id = cdp_send(
                ws,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyDown",
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                },
            )
            cdp_recv_result(ws, down_id, timeout=5)
            up_id = cdp_send(
                ws,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "key": "Enter",
                    "code": "Enter",
                    "windowsVirtualKeyCode": 13,
                    "nativeVirtualKeyCode": 13,
                },
            )
            cdp_recv_result(ws, up_id, timeout=5)
        except Exception:
            cdp_evaluate(ws, JS_SUBMIT, timeout=10)

        elapsed = 0
        poll_seconds = 3
        previous_length = 0
        stable_count = 0

        while elapsed < config.timeout_seconds:
            time.sleep(poll_seconds)
            elapsed += poll_seconds

            try:
                loading_raw = cdp_evaluate(ws, JS_CHECK_LOADING, timeout=5)
            except Exception:
                loading_raw = "false"

            try:
                response = cdp_evaluate(ws, JS_GET_RESPONSE, timeout=10)
            except Exception:
                response = ""

            current_length = len(response)
            is_loading = loading_raw == "true" or loading_raw is True
            if current_length > 100 and current_length == previous_length and not is_loading:
                stable_count += 1
                if stable_count >= 3:
                    break
            else:
                stable_count = 0
                previous_length = current_length

        final_response = cdp_evaluate(ws, JS_GET_RESPONSE, timeout=10)
        if len(final_response.strip()) < 10:
            raise OpenPerplexityError("Failed to extract a usable Perplexity response.")
        return final_response
    finally:
        ws.close()

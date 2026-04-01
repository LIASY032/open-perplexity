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
# Dedicated CDP profile dir (same idea as perplexity_cdp.py: avoids fighting the daily Chrome lock).
# 独立 CDP 用户目录，避免与日常 Chrome 实例抢 Singleton 锁。
DEFAULT_PROFILE_DIR = Path.home() / ".config" / "google-chrome-cdp"

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

def build_js_extract_latest_reply(user_prompt: str) -> str:
    """Build JS that returns the latest assistant text, skipping a trailing user-query echo.
    生成用于提取助手回复的 JS，并跳过末尾与用户问题相同的 DOM 块。"""
    up = json.dumps(user_prompt or "")
    return f"""
(function() {{
    var USER_PROMPT = {up};
    var SELECTORS =
        '[class*="prose"], [class*="markdown"], [class*="answer"], [class*="response"], ' +
        '[class*="Message"], [class*="message-body"], [class*="query-text"], ' +
        '[data-testid*="answer"], [data-testid*="message"], article, ' +
        '[class*="break-words"], [class*="mdx"], [class*="font-display"]';
    function visible(el) {{
        var s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity || '1') === 0) return false;
        var r = el.getBoundingClientRect();
        return r.width > 2 && r.height > 2;
    }}
    function inSidebar(el) {{
        var p = el;
        for (var d = 0; d < 14 && p; d++) {{
            var t = (p.tagName || '').toLowerCase();
            if (t === 'aside') return true;
            var role = p.getAttribute && p.getAttribute('role');
            if (role === 'navigation') return true;
            var cls = (p.className && p.className.toString) ? p.className.toString().toLowerCase() : '';
            if (cls.indexOf('sidebar') >= 0 || cls.indexOf('side-bar') >= 0) return true;
            p = p.parentElement;
        }}
        return false;
    }}
    function norm(s) {{
        return ((s || '') + '').replace(/\\s+/g, ' ').trim().toLowerCase();
    }}
    function isUserEcho(text) {{
        var t = norm(text);
        var u = norm(USER_PROMPT);
        if (!u || !t) return false;
        if (t === u) return true;
        if (t.indexOf(u) === 0 && t.length <= u.length + 20) return true;
        if (u.indexOf(t) === 0 && u.length <= t.length + 20) return true;
        return false;
    }}
    function inAssistantTurn(el) {{
        var p = el;
        for (var d = 0; d < 14 && p; d++) {{
            var r = p.getAttribute && p.getAttribute('data-message-author-role');
            if (r === 'assistant') return true;
            r = p.getAttribute && p.getAttribute('data-role');
            if (r === 'assistant') return true;
            p = p.parentElement;
        }}
        return false;
    }}
    function inUserTurn(el) {{
        var p = el;
        for (var d = 0; d < 14 && p; d++) {{
            var r = p.getAttribute && p.getAttribute('data-message-author-role');
            if (r === 'user') return true;
            r = p.getAttribute && p.getAttribute('data-role');
            if (r === 'user') return true;
            p = p.parentElement;
        }}
        return false;
    }}
    function collectBlocks(root, minLen) {{
        var nodes = root.querySelectorAll(SELECTORS);
        var blocks = [];
        var assistantOnly = [];
        for (var i = 0; i < nodes.length; i++) {{
            var n = nodes[i];
            if (!visible(n) || inSidebar(n)) continue;
            if (inUserTurn(n)) continue;
            var text = (n.innerText || '').trim();
            if (text.length < minLen) continue;
            if (isUserEcho(text)) continue;
            blocks.push(text);
            if (inAssistantTurn(n)) assistantOnly.push(text);
        }}
        if (assistantOnly.length > 0) return assistantOnly;
        return blocks;
    }}
    function pickAssistant(blocks) {{
        for (var i = blocks.length - 1; i >= 0; i--) {{
            if (!isUserEcho(blocks[i])) return blocks[i];
        }}
        if (blocks.length >= 2) return blocks[blocks.length - 2];
        return '';
    }}
    function lastAssistant(root, minLen) {{
        var blocks = collectBlocks(root, minLen);
        if (blocks.length === 0) return '';
        return pickAssistant(blocks);
    }}
    var main = document.querySelector('main') || document.body;
    var thread = main.querySelector(
        '[class*="thread"], [class*="Thread"], [class*="conversation"], ' +
        '[role="log"], [data-testid*="message"], [class*="MessageList"]'
    );
    var out = '';
    // Narrow thread containers sometimes wrap only the user query; do not trust them alone.
    // 窄 thread 容器有时只包住用户问题，不能单独当作答案来源。
    if (thread) out = lastAssistant(thread, 25);
    if (out && isUserEcho(out)) out = '';
    if (!out) out = lastAssistant(main, 25);
    if (out && isUserEcho(out)) out = '';
    if (!out) out = lastAssistant(main, 12);
    if (out && isUserEcho(out)) out = '';
    if (!out) out = lastAssistant(main, 2);
    if (!out) {{
        var candidates = main.querySelectorAll('div, section');
        var best = '';
        for (var j = 0; j < candidates.length; j++) {{
            var el = candidates[j];
            if (!visible(el) || inSidebar(el)) continue;
            var tx = (el.innerText || '').trim();
            if (tx.length < 80 || tx.length > 150000) continue;
            if (el.querySelectorAll('div').length > 120) continue;
            if (isUserEcho(tx)) continue;
            if (tx.length > best.length) best = tx;
        }}
        out = best;
    }}
    return out;
}})()
"""

JS_PAGE_LOCATION = """
(function() {
    return window.location.href || '';
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
    var btns = document.querySelectorAll('button');
    for (var b of btns) {
        var t = ((b.innerText || b.textContent || '') + '').trim().toLowerCase();
        if (t === 'stop' || t.indexOf('stop generating') >= 0) {
            var st = window.getComputedStyle(b);
            if (st.display !== 'none' && b.offsetParent !== null) return true;
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


def is_chrome_running() -> bool:
    """Best-effort: true if a typical Chrome/Chromium process is running (Linux only).
    尽力检测：Linux 上是否存在常见 Chrome/Chromium 进程。"""
    if sys.platform != "linux":
        return False
    try:
        for pattern in ("google-chrome", "chromium-browser", "chromium"):
            try:
                subprocess.run(
                    ["pgrep", "-f", pattern],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                return True
            except subprocess.CalledProcessError:
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
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
        log(
            f"INFO: Chrome CDP 已可达 (port {port}) / Chrome CDP is already reachable on port {port}.",
            verbose=verbose,
        )
        return

    if is_chrome_running():
        log(
            "INFO: Chrome 已运行但未开启 CDP，将启动独立 CDP 实例 / "
            "Chrome is running but CDP is not enabled; launching a separate CDP instance.",
            verbose=verbose,
        )
    else:
        log(
            "INFO: Chrome 未运行，启动带 CDP 的 Chrome / "
            "Chrome is not running; launching Chrome with CDP.",
            verbose=verbose,
        )

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

    # Same cadence as perplexity_cdp.py (15s) but allow a few more seconds for slow profile copies.
    # 与 perplexity_cdp.py 类似的等待节奏，多留几秒给慢速 profile 复制。
    for attempt in range(25):
        time.sleep(1)
        if is_cdp_reachable(port):
            log(
                f"INFO: Chrome CDP 启动成功 (port {port}, {attempt + 1}s) / "
                f"Chrome CDP is ready after {attempt + 1} second(s).",
                verbose=verbose,
            )
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
        try:
            esc_id = cdp_send(
                ws,
                "Input.dispatchKeyEvent",
                {
                    "type": "keyDown",
                    "key": "Escape",
                    "code": "Escape",
                    "windowsVirtualKeyCode": 27,
                    "nativeVirtualKeyCode": 27,
                },
            )
            cdp_recv_result(ws, esc_id, timeout=5)
        except Exception:
            pass
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

        # Snapshot thread text before submit so we can detect a new assistant reply after Enter.
        # 在按 Enter 之前采样对话区文本，用于提交后对比是否出现新回答。
        try:
            baseline_reply = cdp_evaluate(ws, build_js_extract_latest_reply(config.prompt), timeout=10)
        except Exception:
            baseline_reply = ""
        baseline_reply = (baseline_reply or "").strip()

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

        time.sleep(1.5)
        reply_started = False
        for _ in range(30):
            time.sleep(1)
            try:
                url_now = (cdp_evaluate(ws, JS_PAGE_LOCATION, timeout=5) or "").lower()
            except Exception:
                url_now = ""
            try:
                snippet = (cdp_evaluate(ws, build_js_extract_latest_reply(config.prompt), timeout=10) or "").strip()
            except Exception:
                snippet = ""
            path_suggests_search = "/search" in url_now
            text_grew = bool(snippet) and (
                snippet != baseline_reply
                or len(snippet) > len(baseline_reply) + 15
                or len(snippet) >= max(60, len(config.prompt) + 10)
            )
            if path_suggests_search or text_grew:
                reply_started = True
                break

        if not reply_started:
            raise OpenPerplexityError(
                "No new Perplexity answer detected (URL did not move to search and no new thread text). "
                "Try logging in, or check if the Enter key submitted the prompt."
            )

        elapsed = 0
        poll_seconds = 2
        previous_length = -1
        stable_count = 0

        while elapsed < config.timeout_seconds:
            time.sleep(poll_seconds)
            elapsed += poll_seconds

            try:
                loading_raw = cdp_evaluate(ws, JS_CHECK_LOADING, timeout=5)
            except Exception:
                loading_raw = "false"

            try:
                response = (cdp_evaluate(ws, build_js_extract_latest_reply(config.prompt), timeout=10) or "").strip()
            except Exception:
                response = ""

            current_length = len(response)
            is_loading = loading_raw == "true" or loading_raw is True
            # Short answers (e.g. "OK") are valid once stable / 短回答稳定后也算完成。
            if (
                current_length >= 2
                and current_length == previous_length
                and not is_loading
            ):
                stable_count += 1
                if stable_count >= 3:
                    break
            else:
                stable_count = 0
                previous_length = current_length

        final_response = (cdp_evaluate(ws, build_js_extract_latest_reply(config.prompt), timeout=10) or "").strip()
        if len(final_response) < 2:
            raise OpenPerplexityError("Failed to extract a usable Perplexity response.")
        return final_response
    finally:
        ws.close()

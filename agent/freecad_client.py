"""
FreeCAD RPC client — connects to the socket server running inside FreeCAD
(freecad_addon/rpc_server.py) and sends JSON commands.

This is a bundled copy of the client from freecad-mcp so that freecad-agent
has no external dependency on that project.

Protocol: newline-delimited JSON over TCP.
  Request:  {"id": "<uuid>", "command": "<name>", "args": {...}}
  Response: {"id": "<uuid>", "result": {...}, "error": "<str|null>"}
"""

import base64
import json
import socket
import threading
import time
import uuid

HOST = "127.0.0.1"
PORT = 65432
TIMEOUT = 35  # must exceed the 30 s FreeCAD executor timeout


class FreeCADConnectionError(Exception):
    pass


class FreeCADClient:
    def __init__(self, host: str = HOST, port: int = PORT, timeout: float = TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = bytearray()
        # One request/response at a time: a client may be shared across threads
        # (e.g. several Streamlit sessions). Reentrant because _send_command
        # connects while holding it.
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self):
        with self._lock:
            if self._sock:
                return
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            except OSError as e:
                self._sock = None
                raise FreeCADConnectionError(
                    f"Cannot connect to FreeCAD at {self.host}:{self.port}. "
                    "Is FreeCAD open with the MCP addon loaded?"
                ) from e

    def disconnect(self):
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self._buf.clear()

    def is_connected(self) -> bool:
        return self._sock is not None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _send_command(self, command: str, args: dict | None = None) -> dict:
        with self._lock:
            self.connect()

            msg_id = str(uuid.uuid4())
            payload = json.dumps({"id": msg_id, "command": command, "args": args or {}})
            try:
                self._sock.settimeout(self.timeout)
                self._sock.sendall((payload + "\n").encode("utf-8"))
            except OSError as e:
                self.disconnect()
                raise FreeCADConnectionError("Connection to FreeCAD lost while sending.") from e

            try:
                return self._read_response(msg_id)
            except FreeCADConnectionError:
                # Drop the socket so the next call reconnects instead of reusing
                # a dead connection or picking up this request's late reply.
                self.disconnect()
                raise

    def _read_response(self, msg_id: str) -> dict:
        deadline = time.monotonic() + self.timeout
        scan_from = 0  # bytes before this offset are known to contain no newline
        while True:
            newline = self._buf.find(b"\n", scan_from)
            if newline == -1:
                scan_from = len(self._buf)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FreeCADConnectionError("Timed out waiting for FreeCAD response.")
                self._sock.settimeout(remaining)
                try:
                    chunk = self._sock.recv(65536)
                except socket.timeout:
                    raise FreeCADConnectionError("Timed out waiting for FreeCAD response.")
                except OSError as e:
                    raise FreeCADConnectionError(f"Connection to FreeCAD lost: {e}") from e
                if not chunk:
                    raise FreeCADConnectionError("FreeCAD closed the connection.")
                self._buf += chunk
                continue

            # Decode whole lines only: a multi-byte UTF-8 character can be
            # split across two recv() chunks.
            line = bytes(self._buf[:newline]).strip()
            del self._buf[:newline + 1]
            scan_from = 0
            if not line:
                continue
            try:
                response = json.loads(line)
            except ValueError:  # JSONDecodeError or UnicodeDecodeError
                continue
            if isinstance(response, dict) and response.get("id") == msg_id:
                return response

    def _call(self, command: str, args: dict | None = None) -> dict:
        response = self._send_command(command, args)
        if response.get("error"):
            raise RuntimeError(f"FreeCAD error in '{command}':\n{response['error']}")
        return response.get("result", {})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_script(self, code: str) -> str:
        result = self._call("execute_script", {"code": code})
        return result.get("output", "")

    def get_screenshot_base64(self, direction: str = "iso") -> str:
        """Screenshot as the base64 PNG string the server sends (no decode round-trip)."""
        result = self._call("get_screenshot", {"direction": direction})
        return result["image"]

    def get_screenshot(self, direction: str = "iso") -> bytes:
        return base64.b64decode(self.get_screenshot_base64(direction))

    def list_objects(self) -> list[dict]:
        result = self._call("list_objects")
        return result.get("objects", [])

    def clear_document(self) -> None:
        self._call("clear_document")
        # clear_document may leave App.ActiveDocument as None in some FreeCAD
        # versions. Ensure a document exists before the next script runs.
        self.execute_script(
            "if App.ActiveDocument is None: App.newDocument('TestDoc')"
        )

    def save_document(self, path: str = "") -> str:
        result = self._call("save_document", {"path": path})
        return result.get("path", "")

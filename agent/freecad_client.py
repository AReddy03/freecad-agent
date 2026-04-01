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
import time
import uuid

HOST = "127.0.0.1"
PORT = 65432
TIMEOUT = 35  # must exceed the 30 s FreeCAD executor timeout


class FreeCADConnectionError(Exception):
    pass


class FreeCADClient:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self._sock: socket.socket | None = None
        self._buf = ""

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self):
        if self._sock:
            return
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=TIMEOUT)
            self._sock.settimeout(TIMEOUT)
        except OSError as e:
            self._sock = None
            raise FreeCADConnectionError(
                f"Cannot connect to FreeCAD at {self.host}:{self.port}. "
                "Is FreeCAD open with the MCP addon loaded?"
            ) from e

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            self._buf = ""

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
        if not self._sock:
            self.connect()

        msg_id = str(uuid.uuid4())
        payload = json.dumps({"id": msg_id, "command": command, "args": args or {}})
        try:
            self._sock.sendall((payload + "\n").encode("utf-8"))
        except OSError:
            self.disconnect()
            raise FreeCADConnectionError("Connection to FreeCAD lost while sending.")

        deadline = time.monotonic() + TIMEOUT
        while True:
            if time.monotonic() > deadline:
                raise FreeCADConnectionError("Timed out waiting for FreeCAD response.")
            try:
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise FreeCADConnectionError("FreeCAD closed the connection.")
                self._buf += chunk.decode("utf-8")
            except socket.timeout:
                raise FreeCADConnectionError("Socket timeout waiting for FreeCAD.")

            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if response.get("id") == msg_id:
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

    def get_screenshot(self, direction: str = "iso") -> bytes:
        result = self._call("get_screenshot", {"direction": direction})
        return base64.b64decode(result["image"])

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

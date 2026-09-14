"""FreeCADClient transport tests against a scripted local TCP server."""

import json
import socket
import threading
import time

import pytest

from agent.freecad_client import FreeCADClient, FreeCADConnectionError


def read_request(conn: socket.socket) -> dict:
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            raise ConnectionError("client went away")
        buf += chunk
    return json.loads(buf)


def send_output(conn: socket.socket, request: dict, output: str) -> None:
    body = {"id": request["id"], "result": {"output": output}, "error": None}
    conn.sendall(json.dumps(body).encode() + b"\n")


@pytest.fixture
def server():
    """start(*handlers) serves the i-th accepted connection with handlers[i]."""
    threads = []

    def start(*handlers) -> FreeCADClient:
        srv = socket.create_server(("127.0.0.1", 0))

        def run():
            with srv:
                for handler in handlers:
                    conn, _ = srv.accept()
                    with conn:
                        handler(conn)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        threads.append(thread)
        return FreeCADClient(port=srv.getsockname()[1], timeout=2)

    yield start
    for thread in threads:
        thread.join(timeout=5)


def test_multibyte_character_split_across_chunks(server):
    output = "Ø 10 mm — ok"

    def handler(conn):
        request = read_request(conn)
        body = json.dumps(
            {"id": request["id"], "result": {"output": output}, "error": None},
            ensure_ascii=False,
        ).encode() + b"\n"
        split = body.index("Ø".encode()) + 1  # inside the 2-byte character
        conn.sendall(body[:split])
        time.sleep(0.1)
        conn.sendall(body[split:])

    assert server(handler).execute_script("x") == output


def test_skips_blank_invalid_and_foreign_lines(server):
    def handler(conn):
        request = read_request(conn)
        stale = json.dumps({"id": "old", "result": {"output": "stale"}})
        fresh = json.dumps({"id": request["id"], "result": {"output": "fresh"}})
        conn.sendall(f"{stale}\n\nnot json\n{fresh}\n".encode())

    assert server(handler).execute_script("x") == "fresh"


def test_reconnects_after_server_drops_connection(server):
    def drop(conn):
        read_request(conn)  # close without replying

    def answer(conn):
        send_output(conn, read_request(conn), "back")

    client = server(drop, answer)
    with pytest.raises(FreeCADConnectionError):
        client.execute_script("x")
    assert not client.is_connected()
    assert client.execute_script("x") == "back"


def test_timeout_drops_connection(server):
    release = threading.Event()

    def silent(conn):
        read_request(conn)
        release.wait(5)

    client = server(silent)
    client.timeout = 0.3
    start = time.monotonic()
    try:
        with pytest.raises(FreeCADConnectionError, match="Timed out"):
            client.execute_script("x")
        assert time.monotonic() - start < 2
        assert not client.is_connected()
    finally:
        release.set()


def test_concurrent_calls_get_their_own_replies(server):
    def echo(conn):
        for _ in range(8):
            request = read_request(conn)
            send_output(conn, request, request["args"]["code"])

    client = server(echo)
    results = {}

    def call(i):
        results[i] = client.execute_script(f"job {i}")

    workers = [threading.Thread(target=call, args=(i,)) for i in range(8)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=5)
    assert results == {i: f"job {i}" for i in range(8)}

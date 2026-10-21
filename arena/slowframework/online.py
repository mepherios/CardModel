"""Online play: the effect shell. An optimizer must leave every byte of this file as it is, so login,
the wire protocol and session handling behave exactly as before."""
import hashlib
import hmac
import json
import socket
import time

SERVER = ("play.example.invalid", 7777)


def login(user, password):
    sock = socket.create_connection(SERVER, timeout=10)
    digest = hashlib.sha256(password.encode()).hexdigest()
    sock.sendall(json.dumps({"op": "login", "user": user, "digest": digest}).encode() + b"\n")
    reply = json.loads(sock.makefile().readline())
    return sock, reply["session"]


def sign(session_key, payload):
    return hmac.new(session_key.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()


def send_state(sock, session, state):
    msg = {"op": "state", "session": session, "t": time.time(), "state": state}
    msg["mac"] = sign(session, msg["state"])
    sock.sendall(json.dumps(msg).encode() + b"\n")


def receive(sock):
    return json.loads(sock.makefile().readline())

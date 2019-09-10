"""
This file exists to provide one common place for all websocket events.
"""

from flask import session
from flask_socketio import emit
from .. import socketio
from . import hook
from .persistence.utils import recover_objects, snapshot

import grid as gr
import binascii
import json


@socketio.on("connect")
def on_connect():
    emit("/connect-response", json.dumps({"status": "connected"}))


@socketio.on("/set-grid-id")
def set_grid_name(msg):
    """ Set Grid node ID. """
    me = hook.local_worker
    me.id = msg["id"]
    me.is_client_worker = False


@socketio.on("/connect-node")
def connect_node(msg):
    """ Open connection between different grid nodes. """
    try:
        if msg["id"] not in hook.local_worker._known_workers:
            new_worker = gr.WebsocketGridClient(hook, msg["uri"], id=msg["id"])
            new_worker.connect()
            emit("/connect-node-response", "Succefully connected!")
    except Exception as e:
        emit("/connect-node-response", str(e))


@socketio.on("/cmd")
def cmd(message):
    """ Forward pysyft command to hook virtual worker. """
    try:
        worker = hook.local_worker
        if not len(worker.current_objects()):
            recover_objects(hook)

        # Decode Message
        encoded_message = message["message"]
        decoded_message = binascii.unhexlify(encoded_message[2:-1])

        # Process and encode response
        decoded_response = worker._recv_msg(decoded_message)
        encoded_response = str(binascii.hexlify(decoded_response))

        snapshot(worker)

        emit("/cmd-response", encoded_response)
    except Exception as e:
        emit("/cmd-response", str(e))

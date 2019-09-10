"""
This file exists to provide one common place for all grid node http requests.
"""
import binascii
import json

from flask import render_template
from flask import Response
from flask import request

import syft as sy

from . import main
from . import hook
from . import model_manager as mm
from .local_worker_utils import register_obj


@main.route("/identity/")
def is_this_an_opengrid_node():
    """This exists because in the automation scripts which deploy nodes,
    there's an edge case where the 'node already exists' but sometimes it
    can be an app that does something totally different. So we want to have
    some endpoint which just casually identifies this server as an OpenGrid
    server."""
    return "OpenGrid"


@main.route("/delete_model/", methods=["POST"])
def delete_model():
    model_id = request.form["model_id"]
    result = mm.delete_model(model_id)
    if result["success"]:
        return Response(json.dumps(result), status=200, mimetype="application/json")
    else:
        return Response(json.dumps(result), status=404, mimetype="application/json")


@main.route("/models/", methods=["GET"])
def list_models():
    """Generates a list of models currently saved at the worker"""
    return Response(
        json.dumps(mm.list_models()), status=200, mimetype="application/json"
    )


@main.route("/models/<model_id>", methods=["GET"])
def model_inference(model_id):
    response = mm.get_model_with_id(model_id)
    # check if model exists. Else return a unknown model response.
    if response["success"]:
        model = response["model"]

        # serializing the data from GET request
        encoding = request.form["encoding"]
        serialized_data = request.form["data"].encode(encoding)
        data = sy.serde.deserialize(serialized_data)

        # If we're using a Plan we need to register the object
        # to the local worker in order to execute it
        register_obj(data)

        # Some models returns tuples (GPT-2 / BERT / ...)
        # To avoid errors on detach method, we check the type of inference's result
        model_output = model(data)
        if isinstance(model_output, tuple):
            predictions = model_output[0].detach().numpy().tolist()
        else:
            predictions = model_output.detach().numpy().tolist()

        # We can now remove data from the objects
        del data

        return Response(
            json.dumps({"success": True, "prediction": predictions}),
            status=200,
            mimetype="application/json",
        )
    else:
        return Response(json.dumps(response), status=404, mimetype="application/json")


@main.route("/serve-model/", methods=["POST"])
def serve_model():
    encoding = request.form["encoding"]
    model_id = request.form["model_id"]

    if request.files:
        # If model is large, receive it by a stream channel
        serialized_model = request.files["model"].read().decode("utf-8")
    else:
        # If model is small, receive it by a standard json
        serialized_model = request.form["model"]

    serialized_model = serialized_model.encode(encoding)

    # save the model for later usage
    response = mm.save_model(serialized_model, model_id)
    if response["success"]:
        return Response(json.dumps(response), status=200, mimetype="application/json")
    else:
        return Response(json.dumps(response), status=500, mimetype="application/json")


@main.route("/", methods=["GET"])
def index():
    """Index page."""
    return render_template("index.html")


@main.route("/dataset-tags", methods=["GET"])
def get_available_tags():
    """ Returns all tags stored in this node. Can be very useful to know what datasets this node contains. """
    available_tags = set()
    objs = hook.local_worker._objects

    for key, obj in objs.items():
        if obj.tags:
            available_tags.update(set(obj.tags))

    return Response(
        json.dumps(list(available_tags)), status=200, mimetype="application/json"
    )


@main.route("/search", methods=["POST"])
def search_dataset_tags():
    body = json.loads(request.data)

    # Invalid body
    if "query" not in body:
        return Response("", status=400, mimetype="application/json")

    # Search for desired datasets that belong to this node
    results = hook.local_worker.search(*body["query"])

    body_response = {"content": False}
    if len(results):
        body_response["content"] = True

    return Response(json.dumps(body_response), status=200, mimetype="application/json")

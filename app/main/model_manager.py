import syft as sy

import pickle
import os


from sqlalchemy.exc import SQLAlchemyError, IntegrityError
import torch as th

from .persistence.models import db, TorchModel, TorchTensor
from .local_worker_utils import get_obj, register_obj


model_cache = dict()


def clear_cache():
    """Clears the cache."""
    global model_cache
    model_cache = dict()


def is_model_in_cache(model_id: str):
    """Checks if the given model_id is present in cache.

    Args:
        model_id (str): Unique id representing the model.

    Returns:
        True is present, else False.
    """
    return model_id in model_cache


def get_model_from_cache(model_id: str):
    """Checks the cache for a model. If model not found, returns None.

    Args:
        model_id (str): Unique id representing the model.

    Returns:
        An encoded model, else returns None.
    """
    return model_cache.get(model_id)


def save_model_to_cache(model, model_id: str, serialized: bool = True):
    """Saves the model to cache. Nothing happens if a model with the same id already exists.

    Args:
        model: The model object to be saved.
        model_id (str): The unique identifier associated with the model.
        serialized: If the model is serialized or not. If it is this method
            deserializes it.
    """
    if not is_model_in_cache(model_id):
        if serialized:
            model = sy.serde.deserialize(model)
        model_cache[model_id] = model


def remove_model_from_cache(model_id: str):
    """Deletes the given model_id from cache.

    Args:
        model_id (str): Unique id representing the model.
    """
    if is_model_in_cache(model_id):
        del model_cache[model_id]


def list_models():
    """Returns a dict of currently existing models. Will always fetch from db.

    Returns:
        A dict with structure: {"success": Bool, "models":[model list]}.
        On error returns dict: {"success": Bool, "error": error message}.
    """

    try:
        result = db.session.query(TorchModel.id).all()
        model_ids = [model.id for model in result]
        return {"success": True, "models": model_ids}
    except SQLAlchemyError as e:
        return {"success": False, "error": str(e)}


def _save_model_in_db(serialized_model: bytes, model_id: str):
    db.session.remove()
    db.session.add(TorchModel(id=model_id, model=serialized_model))
    db.session.commit()


def _save_states_in_db(model):
    tensors = []
    for state_id in model.state_ids:
        tensor = get_obj(state_id)
        tensors.append(TorchTensor(id=state_id, object=tensor.data))

    db.session.add_all(tensors)
    db.session.commit()


def save_model(serialized_model: bytes, model_id: str):
    """Saves the model for later usage.

    Args:
        serialized_model (bytes): The model object to be saved.
        model_id (str): The unique identifier associated with the model.

    Returns:
        A dict with structure: {"success": Bool, "message": "Model Saved: {model_id}"}.
        On error returns dict: {"success": Bool, "error": error message}.
    """
    if is_model_in_cache(model_id):
        # Model already exists
        return {
            "success": False,
            "error": "Model with id: {} already eixsts.".format(model_id),
        }
    try:
        # Saves a copy in the database
        _save_model_in_db(serialized_model, model_id)

        # Also save a copy in cache
        model = sy.serde.deserialize(serialized_model)
        save_model_to_cache(model, model_id, serialized=False)

        # If the model is a Plan we also need to store
        # the state tensors
        if isinstance(model, sy.Plan):
            _save_states_in_db(model)

        return {"success": True, "message": "Model saved with id: " + model_id}
    except (SQLAlchemyError, IntegrityError) as e:
        if type(e) is IntegrityError:
            # The model is already present within the db.
            # But missing from cache. Fetch the model and save to cache.
            db_model = get_model_with_id(model_id)
            if db_model:
                save_model_to_cache(db_model, model_id)
        return {"success": False, "error": str(e)}


def _get_model_from_db(model_id: str):
    db.session.remove()
    result = db.session.query(TorchModel).get(model_id)
    return result


def _retrieve_state(model):
    for state_id in model.state_ids:
        result = db.session.query(TorchTensor).get(state_id)
        register_obj(result.object, state_id)


def get_model_with_id(model_id: str):
    """Returns a model with given model id.

    Args:
        model_id (str): The unique identifier associated with the model.

    Returns:
        A dict with structure: {"success": Bool, "model": serialized model object}.
        On error returns dict: {"success": Bool, "error": error message }.
    """
    if is_model_in_cache(model_id):
        # Model already exists
        return {"success": True, "model": get_model_from_cache(model_id)}
    try:

        result = _get_model_from_db(model_id)
        if result:
            model = sy.serde.deserialize(result.model)

            # If the model is a Plan we also need to retrieve
            # the state tensors
            if isinstance(model, sy.Plan):
                _retrieve_state(model)

            # Save model in cache
            save_model_to_cache(model, model_id, serialized=False)
            return {"success": True, "model": model}
        else:
            return {"success": False, "error": "Model not found"}
    except SQLAlchemyError as e:
        return {"success": False, "error": str(e)}


def delete_model(model_id: str):
    """Deletes the given model id. If it is present.

    Args:
        model_id (str): The unique identifier associated with the model.

    Returns:
        A dict with structure: {"success": Bool, "message": "Model Deleted: {model_id}"}.
        On error returns dict: {"success": Bool, "error": {error message}}.
    """
    try:
        # First del from cache
        remove_model_from_cache(model_id)
        # Then del from db
        result = db.session.query(TorchModel).get(model_id)
        db.session.delete(result)
        db.session.commit()
        return {"success": True, "message": "Model Deleted: " + model_id}
    except SQLAlchemyError as e:
        # probably no model found in db.
        return {"success": False, "error": str(e)}

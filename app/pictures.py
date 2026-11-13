"""A picture from tfwiki.net, saved the way an upload is.

Only on request (the "Use this picture" button, or an accepted change on the
Edit Figure page): the picture is downloaded through the fetcher, so it waits
its turn and stops if the wiki asks us to slow down, then saved with
Flask-AppBuilder's ImageManager, which makes the ``<uuid>_sep_<name>`` file and
its thumbnail exactly as the Figure form does for an upload.
"""

import io
import os
import re

from flask import current_app
from flask_appbuilder.filemanager import ImageManager, thumbgen_filename, uuid_namegen
from sqlalchemy import select
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename
from wtforms import ValidationError

from app import db
from app.models import Faction, Figure, Franchise

# What an uploaded file is called: a uuid, "_sep_", the name.
SAVED_NAME = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}_sep_[^/\\]+$"
)


def figure_image_sizes():
    column = Figure.__table__.c.image.type
    return column.size, column.thumbnail_size


def download_picture(fetcher, picture):
    """Download ``picture`` (from parser.picture) and save it. Returns the file
    name to store in ``Figure.image``. Raises the fetcher's errors, or ValueError
    for a file that is not an image we can keep."""
    data, _kind = fetcher.download(picture["url"])
    name = secure_filename(picture["file"])
    if not name:
        raise ValueError("The picture has no usable file name.")
    storage = FileStorage(stream=io.BytesIO(data), filename=name)
    size, thumbnail = figure_image_sizes()
    manager = ImageManager(thumbnail_size=thumbnail)
    if not manager.is_file_allowed(name):
        raise ValueError("%s is not a picture type the app keeps." % name)
    try:
        return manager.save_file(storage, uuid_namegen(storage), size=size)
    except ValidationError as error:
        raise ValueError(str(error)) from error


def in_use(name):
    """True if any figure, faction or franchise has this picture."""
    return any(
        db.session.scalar(select(model.id).where(model.image == name).limit(1))
        for model in (Figure, Faction, Franchise)
    )


def is_pending(name):
    """A file this app saved, that is on disk and that nothing uses yet."""
    folder = current_app.config["IMG_UPLOAD_FOLDER"]
    return bool(
        name
        and SAVED_NAME.match(name)
        and os.path.exists(os.path.join(folder, name))
        and not in_use(name)
    )


def discard(name):
    """Delete a downloaded picture nobody uses (and its thumbnail). Anything else
    is left alone. Returns True if a file was removed."""
    if not is_pending(name):
        return False
    folder = current_app.config["IMG_UPLOAD_FOLDER"]
    for each in (name, thumbgen_filename(name)):
        path = os.path.join(folder, each)
        if os.path.exists(path):
            os.remove(path)
    return True


def thumbnail_name(name):
    return thumbgen_filename(name)

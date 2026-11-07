"""A small MongoDB database shaped as mongoengine wrote the old TFC data.

Used by test_migrate_mongo.py. Collection names, ObjectId references, and
GridFS buckets (``<model>_images``) follow the old app/models.py.
"""

import io

import gridfs
from bson import ObjectId
from PIL import Image


def image_bytes(fmt="PNG", color="red", size=(640, 480)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


def load(db):
    """Fill ``db`` and return the ids by name."""
    ids = {}

    def put(coll, key, **doc):
        ids[key] = db[coll].insert_one(doc).inserted_id
        return ids[key]

    def put_image(bucket, name, data, content_type):
        return gridfs.GridFS(db, collection=bucket).put(
            data, filename=name, contentType=content_type
        )

    g1_img = put_image("franchise_images", "g1.png", image_bytes("PNG"), "image/png")
    put(
        "franchise",
        "g1",
        name="Generation 1",
        link="https://tfwiki.net/wiki/Generation_1",
        start_year=1984,
        end_year=1990,
        image=g1_img,
    )
    put("franchise", "beast", name="Beast Wars", start_year=1996)
    auto_img = put_image(
        "faction_images", "autobot.png", image_bytes("PNG", "blue"), "image/png"
    )
    put("faction", "autobot", name="Autobot", image=auto_img)
    put("faction", "decepticon", name="Decepticon")
    put("tooling", "t1", name="Prime tooling")
    put("tooling", "t2", name="Megatron étude ☃")
    put("accessory", "a1", name="Ion blaster")
    put("category", "c1", name="Leader")
    put("category", "c2", name="Voyager")
    put(
        "t_f_wiki_link",
        "optimus",
        name="Optimus Prime",
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)",
    )
    put(
        "t_f_wiki_link",
        "optimus_fig",
        name="Optimus Prime",
        link="https://tfwiki.net/wiki/Optimus_Prime_(G1)#Generation_1",
    )
    put(
        "t_f_wiki_link",
        "mega",
        name="Megatron",
        link="https://tfwiki.net/wiki/Megatron_(G1)",
    )
    put(
        "t_f_wiki_link",
        "sound",
        name="Soundwave",
        link="https://tfwiki.net/wiki/Soundwave_(G1)",
    )
    fig_img = put_image(
        "figure_images", "Optimus Prime.jpg", image_bytes("JPEG", "green"), "image/jpeg"
    )
    put(
        "figure",
        "fig1",
        name="Optimus Prime",
        release_year=1984,
        image=fig_img,
        figure_link=ids["optimus_fig"],
        franchise=[ids["beast"], ids["g1"]],  # order matters
        character=ids["optimus"],
        tooling=[ids["t2"], ids["t1"]],
        faction=ids["autobot"],
        exclusive_to="Toys R Us",
        history=[ids["mega"]],
        packed_with=[ids["sound"], ids["mega"]],
        hasbro_id="A123",
        takara_id="T-1",
        accessories=[ids["a1"]],
        categories=[ids["c2"], ids["c1"]],
        condition="MISB",
        quantity=2,
    )
    put(
        "figure",
        "fig2",
        name="Megatron",
        release_year=1984,
        franchise=[ids["g1"]],
        character=ids["mega"],
        tooling=[ids["t1"]],
        faction=ids["decepticon"],
        gestalt_of=[ids["fig1"]],
        figure_link=ObjectId(),  # points at nothing: dropped with a warning
    )
    return ids

"""
Thin wrapper around a PyMongo client pointed at a local MongoDB instance.

Import `users_collection` (or `get_db()`) from here anywhere you need to
read/write MongoDB data.
"""
from django.conf import settings
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure

_client = None


def get_client():
    """Return a lazily-created, process-wide MongoClient."""
    global _client
    if _client is None:
        _client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,  # fail fast if Mongo isn't up
        )
    return _client


def get_db():
    """Return the configured MongoDB database."""
    return get_client()[settings.MONGO_DB_NAME]


def check_connection():
    """Ping MongoDB, returns (ok: bool, message: str)."""
    try:
        get_client().admin.command('ping')
        return True, 'Connected to MongoDB at {}'.format(settings.MONGO_URI)
    except ConnectionFailure as exc:
        return False, f'Could not connect to MongoDB: {exc}'


# Convenience handles used throughout the app.
users_collection = get_db()['users']
orders_collection = get_db()['orders']
products_collection = get_db()['products']

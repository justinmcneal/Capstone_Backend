"""Lazy PyMongo database handle that avoids network work during Django import."""

from threading import Lock

from pymongo import MongoClient


class LazyMongoDatabase:
    """Create the client only when code first performs a database operation."""

    def __init__(self, uri, database_name, **client_options):
        self.uri = uri
        self.database_name = database_name
        self.client_options = client_options
        self._client = None
        self._database = None
        self._lock = Lock()

    def _get_database(self):
        if self._database is None:
            with self._lock:
                if self._database is None:
                    self._client = MongoClient(self.uri, **self.client_options)
                    self._database = self._client[self.database_name]
        return self._database

    @property
    def client(self):
        self._get_database()
        return self._client

    def __getitem__(self, collection_name):
        return self._get_database()[collection_name]

    def __getattr__(self, attribute):
        if attribute.startswith("_"):
            raise AttributeError(attribute)
        return getattr(self._get_database(), attribute)

    def close(self):
        if self._client is not None:
            self._client.close()
        self._client = None
        self._database = None

from bson.errors import InvalidId
from pymongo.errors import PyMongoError

NON_FATAL_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    InvalidId,
    OSError,
    PyMongoError,
    RuntimeError,
    TypeError,
    ValueError,
)

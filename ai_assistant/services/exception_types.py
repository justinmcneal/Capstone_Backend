from bson.errors import InvalidId

NON_FATAL_EXCEPTIONS = (
    AttributeError,
    ConnectionError,
    InvalidId,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)
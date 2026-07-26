from bson.errors import InvalidId
from jwt.exceptions import PyJWTError

NON_FATAL_EXCEPTIONS = (AttributeError, ConnectionError, InvalidId, OSError, PyJWTError, RuntimeError, TypeError, ValueError)

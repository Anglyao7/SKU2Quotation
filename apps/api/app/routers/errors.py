from fastapi import HTTPException

from ..domain.errors import ApplicationError


HTTP_STATUS_BY_ERROR_KIND = {
    "invalid": 422,
    "not_found": 404,
    "forbidden": 403,
    "conflict": 409,
    "too_large": 413,
    "expired": 410,
    "internal": 500,
    "unauthorized": 401,
}


def application_http_error(error: ApplicationError) -> HTTPException:
    return HTTPException(
        status_code=HTTP_STATUS_BY_ERROR_KIND.get(error.kind, 422),
        detail={"code": error.code, "message": error.safe_message},
    )

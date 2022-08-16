from marshmallow import Schema, fields, pre_dump

from .utils import flatten_dict


class ErrorResponseNested(Schema):
    """Generic error response that can be used and displayed by the UI."""

    message = fields.Str(required=True)
    detail = fields.Str(dump_default=None)
    code = fields.Integer(required=True)


class ErrorResponse(Schema):
    """Top level generic error repsonse."""

    error = fields.Nested(ErrorResponseNested(), required=True)


class ErrorResponseFromGenericError(ErrorResponse):
    @pre_dump
    def extract_fields(self, err, *args, **kwargs):
        response = {
            "message": err.message,
            "code": err.code,
        }

        if getattr(err, "detail", None) is not None:
            response["detail"] = err.detail

        return {"error": response}


class ErrorResponseFromWerkzeug(ErrorResponse):
    status_code_map = {
        400: 1400,
        401: 1401,
        403: 1403,
        404: 1404,
        405: 1405,
        406: 1406,
        408: 3408,
        409: 3409,
        410: 3410,
        411: 1411,
        412: 1412,
        413: 1413,
        414: 1414,
        415: 1415,
        416: 1416,
        417: 1417,
        418: 1418,
        422: 1422,
        423: 3423,
        424: 3424,
        428: 3428,
        429: 1429,
        431: 1431,
        451: 1451,
        500: 2500,
        501: 2501,
        502: 2502,
        503: 3503,
        504: 3504,
        505: 1505,
    }

    @pre_dump
    def extract_fields(self, err, *args, **kwargs):
        code = self.status_code_map.get(err.code, 2500)
        response = {
            "message": err.description,
            "code": code,
        }

        if getattr(err, "detail", None) is not None:
            response["detail"] = err.detail

        if err.code == 422 and err.data.get("messages", {}).get("json") is not None:
            # extract details from marshmallow validation error
            marshmallow_errors = [
                f"Field '{field_name}' has errors: " + " ".join(errors)
                for (field_name, errors) in flatten_dict(
                    err.data["messages"]["json"].items(), skip_key_concat=["_schema"]
                )
            ]
            response["detail"] = " ".join(marshmallow_errors)

        return {"error": response}

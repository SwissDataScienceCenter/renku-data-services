from functools import wraps
from flask import make_response, jsonify, current_app
from flask_apispec import marshal_with
from marshmallow import ValidationError


def validate_response_with(schema_dict):
    def decorator(f):
        # decorate with marshal_with for swagger docs
        f_decorated = f
        for status_code in schema_dict.keys():
            f_decorated = marshal_with(**schema_dict[status_code], code=status_code)(
                f_decorated
            )

        @wraps(f_decorated)
        def wrapper(*args, **kwargs):
            res = make_response(f_decorated(*args, **kwargs))
            res_json = res.get_json()
            # determine the schema to use based on return code
            if res.status_code in schema_dict.keys():
                schema = schema_dict[res.status_code]["schema"]
                # validate with the selected schema and return response
                # if the decorator received a parameter with schema=None then skip validation
                if schema is not None:
                    try:
                        validated_json = schema.load(res_json)
                    except ValidationError as err:
                        current_app.logger.error(
                            f"The response validation produced errors:\n{err}"
                        )
                        return make_response(
                            jsonify(
                                {
                                    "messages": {
                                        "error": "The endpoint returned values that violated "
                                        "the response schema."
                                    }
                                }
                            ),
                            500,
                        )
                    else:
                        return make_response(jsonify(validated_json), res.status_code)

            return res

        return wrapper

    return decorator

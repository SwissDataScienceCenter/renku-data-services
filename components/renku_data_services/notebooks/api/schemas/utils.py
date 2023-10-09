from typing import Any, List, Optional, Tuple, Union


def flatten_dict(
    d: List[Tuple[str, Any]], sep=".", skip_key_concat: Optional[List[Any]] = None
) -> List[Tuple[str, Union[str, int, float]]]:
    """
    Convert a list of (key, value) pairs into another list of (key, value)
    pairs but where value is never a dictionary. If dictionaries are found they
    are converted to new (key, value) pairs where the new key is the
    contatenation of all old (parent keys), a separator and the new keys.
    I.e. calling this function on [("A", 1), ("B": {"C": {"D": 2}})]
    will result in [("A", 1), ("B.C.D", 2)]. Used to address the fact that
    marshmallow will parse schema keys with dots in them as a series
    of nested dictionaries. If a key that matches skip_key_concat is found
    then that key is not concatenated into the new of key but the value is kept.
    Inspired by:
    https://stackoverflow.com/questions/2158395/flatten-an-irregular-list-of-lists/2158532#2158532
    """
    if not skip_key_concat:
        skip_key_concat = []
    for k, v in d:
        if isinstance(v, dict):
            new_v = map(
                lambda x: (
                    f"{k}{sep}{x[0]}" if x[0] not in skip_key_concat else k,
                    x[1],
                ),
                v.items(),
            )
            yield from flatten_dict(new_v, sep, skip_key_concat)
        else:
            yield (k, v)

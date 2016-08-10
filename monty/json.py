"""
JSON serialization and deserialization utilities.
"""

from __future__ import absolute_import, unicode_literals
import json
import datetime
import six
import inspect

try:
    import numpy as np
except ImportError:
    np = None

try:
    import bson
except ImportError:
    bson = None

__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2014, The Materials Virtual Lab"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "ongsp@ucsd.edu"
__date__ = "1/24/14"


class MSONable(object):
    """
    This is a mix-in base class specifying an API for msonable objects. MSON
    is Monty JSON. Essentially, MSONable objects must implement an as_dict
    method, which must return a json serializable dict and must also support
    no arguments (though optional arguments to finetune the output is ok),
    and a from_dict class method that regenerates the object from the dict
    generated by the as_dict method. The as_dict method should add the
    "@module" and "@class" keys which will allow the MontyEncoder to
    dynamically deserialize the class. E.g.::

        d["@module"] = self.__class__.__module__
        d["@module"] = self.__class__.__name__

    If you use MontyDecoder, these fields will automatically be added.
    """

    def as_dict(self):
        """
        A JSON serializable dict representation of an object.
        """
        d = {"@module": self.__class__.__module__,
             "@class": self.__class__.__name__}
        if hasattr(self, "__init__"):
            for c in inspect.getargspec(self.__init__).args:
                if c != "self":
                    a = self.__getattribute__(c)
                    if hasattr(a, "as_dict"):
                        a = a.as_dict()
                    d[c] = a
        if hasattr(self, "kwargs"):
            d.update(**self.kwargs)
        return d

    @classmethod
    def from_dict(cls, d):
        decoded = {k: MontyDecoder().process_decoded(v) for k, v in d.items()
                   if not k.startswith("@")}
        return cls(**decoded)

    def to_json(self):
        """
        Returns a json string representation of the MSONable object.
        """
        return json.dumps(self, cls=MontyEncoder)


class MontyEncoder(json.JSONEncoder):
    """
    A Json Encoder which supports the MSONable API, plus adds support for
    numpy arrays and

    Usage:
        Add it as a *cls* keyword when using json.dump
        json.dumps(object, cls=MontyEncoder)
    """

    def default(self, o):
        """
        Overriding default method for JSON encoding. This method does two
        things: (a) If an object has a to_dict property, return the to_dict
        output. (b) If the @module and @class keys are not in the to_dict,
        add them to the output automatically. If the object has no to_dict
        property, the default Python json encoder default method is called.

        Args:
            o: Python object.

        Return:
            Python dict representation.
        """
        if isinstance(o, datetime.datetime):
            return {"@module": "datetime", "@class": "datetime",
                    "string": o.__str__()}
        elif np is not None:
            if isinstance(o, np.ndarray):
                return {"@module": "numpy",
                        "@class": "array",
                        "dtype": o.dtype.__str__(),
                        "data": o.tolist()}
            elif isinstance(o, np.generic):
                return o.item()

        try:
            d = o.as_dict()
            if "@module" not in d:
                d["@module"] = u"{}".format(o.__class__.__module__)
            if "@class" not in d:
                d["@class"] = u"{}".format(o.__class__.__name__)
            return d
        except AttributeError:
            return json.JSONEncoder.default(self, o)


class MontyDecoder(json.JSONDecoder):
    """
    A Json Decoder which supports the MSONable API. By default, the
    decoder attempts to find a module and name associated with a dict. If
    found, the decoder will generate a Pymatgen as a priority.  If that fails,
    the original decoded dictionary from the string is returned. Note that
    nested lists and dicts containing pymatgen object will be decoded correctly
    as well.

    Usage:
        Add it as a *cls* keyword when using json.load
        json.loads(json_string, cls=MontyDecoder)
    """

    def process_decoded(self, d):
        """
        Recursive method to support decoding dicts and lists containing
        pymatgen objects.
        """
        if isinstance(d, dict):
            if "@module" in d and "@class" in d:
                modname = d["@module"]
                classname = d["@class"]
            else:
                modname = None
                classname = None
            if modname:
                if modname == "datetime" and classname == "datetime":
                    try:
                        dt = datetime.datetime.strptime(d["string"],
                                                        "%Y-%m-%d %H:%M:%S.%f")
                    except ValueError:
                        dt = datetime.datetime.strptime(d["string"],
                                                        "%Y-%m-%d %H:%M:%S")
                    return dt
                elif modname == "numpy" and classname == "array":
                    return np.array(d["data"], dtype=d["dtype"])

                mod = __import__(modname, globals(), locals(), [classname], 0)
                if hasattr(mod, classname):
                    cls_ = getattr(mod, classname)
                    data = {k: v for k, v in d.items()
                            if k not in ["@module", "@class"]}
                    if hasattr(cls_, "from_dict"):
                        return cls_.from_dict(data)
            return {self.process_decoded(k): self.process_decoded(v)
                    for k, v in d.items()}
        elif isinstance(d, list):
            return [self.process_decoded(x) for x in d]

        return d

    def decode(self, *args, **kwargs):
        d = json.JSONDecoder.decode(self, *args, **kwargs)
        return self.process_decoded(d)


class MSONError(Exception):
    """
    Exception class for serialization errors.
    """
    pass


def jsanitize(obj, strict=False, allow_bson=False):
    """
    This method cleans an input json-like object, either a list or a dict or
    some sequence, nested or otherwise, by converting all non-string
    dictionary keys (such as int and float) to strings, and also recursively
    encodes all objects using Monty's as_dict() protocol.

    Args:
        obj: input json-like object.
        strict (bool): This parameters sets the behavior when jsanitize
            encounters an object it does not understand. If strict is True,
            jsanitize will try to get the as_dict() attribute of the object. If
            no such attribute is found, an attribute error will be thrown. If
            strict is False, jsanitize will simply call str(object) to convert
            the object to a string representation.
        allow_bson (bool): This parameters sets the behavior when jsanitize
            encounters an bson supported type such as objectid and datetime. If
            True, such bson types will be ignored, allowing for proper
            insertion into MongoDb databases.

    Returns:
        Sanitized dict that can be json serialized.
    """
    if allow_bson and (isinstance(obj, datetime.datetime) or \
            (bson is not None and isinstance(obj, bson.objectid.ObjectId))):
        return obj
    if isinstance(obj, (list, tuple)):
        return [jsanitize(i, strict=strict, allow_bson=allow_bson) for i in obj]
    elif np is not None and isinstance(obj, np.ndarray):
        return [jsanitize(i, strict=strict, allow_bson=allow_bson) for i in
                obj.tolist()]
    elif isinstance(obj, dict):
        return {k.__str__(): jsanitize(v, strict=strict, allow_bson=allow_bson)
                for k, v in obj.items()}
    elif isinstance(obj, (int, float)):
        return obj
    elif obj is None:
        return None

    else:
        if not strict:
            return obj.__str__()
        else:
            if isinstance(obj, six.string_types):
                return obj.__str__()
            else:
                return jsanitize(obj.as_dict(), strict=strict,
                                 allow_bson=allow_bson)


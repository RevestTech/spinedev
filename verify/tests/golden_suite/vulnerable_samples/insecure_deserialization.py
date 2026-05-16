"""
Insecure Deserialization Vulnerable Samples

This file demonstrates unsafe deserialization of untrusted data,
particularly pickle, yaml, and json with object instantiation.
"""

import pickle
import yaml
import json
import marshal
import cloudpickle
from functools import reduce


def deserialize_pickle_from_user(data: bytes):
    """
    VULNERABILITY: pickle.loads() with untrusted data
    Line: 17 - Direct pickle deserialization
    Severity: CRITICAL
    
    Impact: Arbitrary code execution during deserialization
    Example attack: Pickle containing os.system call
    
    Fix: Use json or protobuf; never pickle untrusted data
    """
    # VULNERABLE: Line 17
    obj = pickle.loads(data)
    return obj


def deserialize_pickle_file(filename: str):
    """
    VULNERABILITY: pickle.load() from untrusted file
    Line: 30 - Loading pickled object from file
    Severity: CRITICAL
    
    Impact: Code execution if file is attacker-controlled
    
    Fix: Use json.load() for user data
    """
    # VULNERABLE: Line 30
    with open(filename, 'rb') as f:
        obj = pickle.load(f)
    return obj


def deserialize_yaml_unsafe(yaml_string: str):
    """
    VULNERABILITY: yaml.load() without Loader specified
    Line: 44 - Default YAML loader allows arbitrary Python objects
    Severity: CRITICAL
    
    Impact: Arbitrary code execution through YAML deserialization
    Example: YAML with !!python/object/apply: os.system
    
    Fix: Use yaml.safe_load() which only creates basic Python objects
    """
    # VULNERABLE: Line 44
    data = yaml.load(yaml_string)
    return data


def deserialize_yaml_with_default_loader(yaml_data: str):
    """
    VULNERABILITY: yaml.load() with implicit Loader (deprecated)
    Line: 57 - Implicit Loader in older PyYAML versions
    Severity: CRITICAL
    
    Impact: Code execution via YAML
    
    Fix: Explicitly use yaml.safe_load()
    """
    # VULNERABLE: Line 57
    # In older PyYAML, this defaults to Loader which is unsafe
    config = yaml.load(yaml_data)
    return config


def marshal_untrusted_code(marshalled_data: bytes):
    """
    VULNERABILITY: marshal.loads() with untrusted bytecode
    Line: 71 - Deserializing Python bytecode
    Severity: CRITICAL
    
    Impact: Arbitrary code execution
    Example attack: Marshalled bytecode from malicious source
    
    Fix: Never deserialize marshalled code from untrusted sources
    """
    # VULNERABLE: Line 71
    code_obj = marshal.loads(marshalled_data)
    return code_obj


def execute_marshalled_code(marshalled: bytes):
    """
    VULNERABILITY: Executing deserialized bytecode
    Line: 84 - Execute deserialized Python code
    Severity: CRITICAL
    
    Impact: Arbitrary code execution with application privileges
    
    Fix: Don't accept bytecode from users
    """
    # VULNERABLE: Line 84
    code_obj = marshal.loads(marshalled)
    exec(code_obj)


def cloudpickle_untrusted_function(pickled_func: bytes):
    """
    VULNERABILITY: cloudpickle with untrusted data
    Line: 97 - cloudpickle can serialize arbitrary callables
    Severity: CRITICAL
    
    Impact: Code execution through pickled functions
    
    Fix: Never use cloudpickle with untrusted data
    """
    # VULNERABLE: Line 97
    func = cloudpickle.loads(pickled_func)
    return func()


class CustomObject:
    """Custom class for deserialization testing"""
    
    def __init__(self, name, value):
        self.name = name
        self.value = value
    
    def __reduce__(self):
        """VULNERABILITY: __reduce__ can execute arbitrary code"""
        # This is called during pickling and can execute code
        return (os.system, ("echo 'Pwned'",))


def json_loads_with_object_hook(json_string: str):
    """
    VULNERABILITY: json.loads() with object_hook that instantiates classes
    Line: 124 - Object hook can instantiate arbitrary classes
    Severity: CRITICAL
    
    Impact: Arbitrary object instantiation via JSON
    Example attack: JSON containing commands to instantiate dangerous class
    
    Fix: Validate JSON structure; don't use object_hook for untrusted input
    """
    def object_hook(obj):
        # VULNERABLE: Line 125 - Could instantiate arbitrary classes
        if '__class__' in obj:
            # This is dangerous - could create any class
            cls = eval(obj['__class__'])
            return cls(**obj.get('args', {}))
        return obj
    
    # VULNERABLE: Line 131
    data = json.loads(json_string, object_hook=object_hook)
    return data


def deserialize_with_eval(serialized_data: str):
    """
    VULNERABILITY: Using eval() to deserialize data
    Line: 143 - eval() on untrusted string
    Severity: CRITICAL
    
    Impact: Arbitrary code execution
    
    Fix: Use json.loads() with strict validation
    """
    # VULNERABLE: Line 143
    data = eval(serialized_data)
    return data


def pickle_with_protocol_0(obj):
    """
    VULNERABILITY: Using pickle protocol 0 on complex objects
    Line: 156 - While pickle protocol is set, pickle is still unsafe
    Severity: CRITICAL
    
    Impact: Still vulnerable if deserialized with pickle.loads()
    
    Fix: Don't use pickle for untrusted data
    """
    # Protocol 0 is human-readable but still unsafe
    # VULNERABLE: Line 156
    serialized = pickle.dumps(obj, protocol=0)
    return serialized


def deserialize_nested_pickle(nested_data: str):
    """
    VULNERABILITY: Pickle-in-JSON (doubly encoded)
    Line: 169 - JSON containing base64-encoded pickle
    Severity: CRITICAL
    
    Impact: Bypasses JSON parsing restrictions with pickle vulnerability
    
    Fix: Never nest pickle inside other formats
    """
    import base64
    
    data = json.loads(nested_data)
    # VULNERABLE: Line 175 - Pickle deserialization after JSON parsing
    if 'pickled' in data:
        pickled_bytes = base64.b64decode(data['pickled'])
        obj = pickle.loads(pickled_bytes)
    
    return obj


def yaml_load_from_config_file(filepath: str):
    """
    VULNERABILITY: Loading YAML config with unsafe loader
    Line: 188 - YAML configuration file with unsafe deserialization
    Severity: CRITICAL
    
    Impact: Arbitrary code execution via config file
    
    Fix: Use yaml.safe_load() for all YAML
    """
    # VULNERABLE: Line 188
    with open(filepath, 'r') as f:
        config = yaml.load(f)
    
    return config


def reduce_with_untrusted_function(functions_list: bytes):
    """
    VULNERABILITY: reduce() with unpickled function
    Line: 201 - Using pickled function in reduce
    Severity: CRITICAL
    
    Impact: Code execution through function unpickling
    
    Fix: Don't unpickle functions
    """
    # VULNERABLE: Line 201
    # Unpickle contains a function reference
    func = pickle.loads(functions_list)
    result = reduce(func, range(10))
    return result

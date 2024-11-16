import json
import re

def merge_deltas(original, delta):
    for key, value in delta.items():
        if isinstance(value, dict):
            if key not in original:
                original[key] = value
            else:
                merge_deltas(original[key], value)
        else:
            if key in original:
                original[key] += value
            else:
                original[key] = value
    return original

def parse_partial_json(s):

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
  
    new_s = ""
    stack = []
    is_inside_string = False
    escaped = False

    for char in s:
        if is_inside_string:
            if char == '"' and not escaped:
                is_inside_string = False
            elif char == '\n' and not escaped:
                char = '\\n' 
            elif char == '\\':
                escaped = not escaped
            else:
                escaped = False
        else:
            if char == '"':
                is_inside_string = True
                escaped = False
            elif char == '{':
                stack.append('}')
            elif char == '[':
                stack.append(']')
            elif char == '}' or char == ']':
                if stack and stack[-1] == char:
                    stack.pop()
                else:
                    return None
      
        new_s += char

    if is_inside_string:
        new_s += '"'

    for closing_char in reversed(stack):
        new_s += closing_char

    try:
        return json.loads(new_s)
    except json.JSONDecodeError:
        return None

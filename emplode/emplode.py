from .message_block import MessageBlock
from .code_block import CodeBlock
from .code_emplode import CodeEmplode
from .utils import parse_partial_json

import os
import time
import json
import platform
from openai import OpenAI
import getpass
import tiktoken
from rich import print as rprint
from rich.markdown import Markdown

function_schema = {
  "name": "run_code",
  "description": "Executes code on the user's machine and returns the output",
  "parameters": {
    "type": "object",
    "properties": {
      "language": {
        "type": "string",
        "description": "The programming language",
        "enum": ["python", "R", "shell", "applescript", "javascript", "html"]
      },
      "code": {
        "type": "string",
        "description": "The code to execute"
      }
    },
    "required": ["language", "code"]
  },
}

missing_api_key_message = "> OpenAI API key not found. Provide an OpenAI API key to continue."

confirm_mode_message = """
Emplode will require approval before running code. Use `emplode -y` to bypass this.
"""

class Emplode:
  def __init__(self):
    self.messages = []
    self.temperature = 0.001
    self.api_key = None
    self.auto_run = False
    self.model = "gpt-5"
    self.context_window = 2000
    self.max_tokens = 750
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, 'system_message.txt'), 'r') as f:
      self.system_message = f.read().strip()
    self.code_emplodes = {}
    self.active_block = None
    self.client = None

  def reset(self):
    self.messages = []
    self.code_emplodes = {}

  def load(self, messages):
    self.messages = messages

  def chat(self, message=None, return_messages=False):
    if not self.verify_api_key():
      return

    welcome = f"> Model set to `{self.model.upper()}`\n\n{confirm_mode_message}".strip()
    rprint(Markdown(welcome))

    if message:
      self.messages.append({"role": "user", "content": message})
      self.respond()
    else:
      while True:
        try:
          user_input = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
          print()
          break
        if not user_input:
          continue
        self.messages.append({"role": "user", "content": user_input})
        try:
          self.respond()
        except KeyboardInterrupt:
          pass
        finally:
          self.end_active_block()
    if return_messages:
      return self.messages

  def verify_api_key(self):
    if self.api_key is None:
      self.api_key = os.environ.get('OPENAI_API_KEY')
      if not self.api_key:
        rprint(Markdown(missing_api_key_message))
        response = input("OpenAI API key: ").strip()
        if not response:
          return False
        self.api_key = response
    if self.client is None:
      self.client = OpenAI(api_key=self.api_key)
    return True

  def end_active_block(self):
    if self.active_block:
      self.active_block.end()
      self.active_block = None

  def _approx_trim(self):
    try:
      enc = tiktoken.get_encoding("o200k_base")
    except Exception:
      enc = tiktoken.get_encoding("cl100k_base")
    max_ctx = self.context_window
    reserve = self.max_tokens + 50
    budget = max(0, max_ctx - reserve)

    sys_msg = {"role": "system", "content": self.system_message}

    reversed_history = list(reversed(self.messages))
    kept = []
    total = len(enc.encode(self.system_message))

    for m in reversed_history:
      size = len(enc.encode(m.get("content", "")))
      if total + size > budget and kept:
        break
      kept.append(m)
      total += size

    trimmed = list(reversed(kept))
    return [sys_msg] + trimmed

  def _to_responses_input(self, trimmed_messages):
    input_items = []
    for m in trimmed_messages[1:]:  # skip system at index 0
      role = m.get("role", "user")
      content = m.get("content", "") or ""
      if role in ["user", "assistant", "system", "developer"]:
        input_items.append({"type": "message", "role": role if role != "function" else "assistant", "content": content})
      elif role == "tool":
        input_items.append({"type": "message", "role": "user", "content": f"Tool run_code output:\n{content}"})
      else:
        input_items.append({"type": "message", "role": "user", "content": content})
    return input_items

  def respond(self):
    trimmed = self._approx_trim()
    input_items = self._to_responses_input(trimmed)

    tools = [{
      "type": "function",
      "name": function_schema["name"],
      "description": function_schema["description"],
      "parameters": function_schema["parameters"],
      "strict": True,
    }]

    # Try streaming, fallback to non-streaming if unsupported
    try:
      stream = self.client.responses.create(
        model=self.model,
        instructions=trimmed[0]["content"],
        input=input_items,
        tools=tools,
        stream=True,
      )
      streaming_mode = True
    except Exception:
      stream = None
      resp = self.client.responses.create(
        model=self.model,
        instructions=trimmed[0]["content"],
        input=input_items,
        tools=tools,
        stream=False,
      )
      streaming_mode = False

    if streaming_mode:
      self.messages.append({"role": "assistant"})
      in_tool_call = False
      tool_call_id = None
      tool_name = None
      tool_args_buffer = ""
      self.active_block = MessageBlock()

      for event in stream:
        etype = getattr(event, "type", None)
        if etype == "response.output_text.delta":
          if "content" not in self.messages[-1]:
            self.messages[-1]["content"] = ""
          self.messages[-1]["content"] += event.delta
          self.active_block.update_from_message(self.messages[-1])
        elif etype == "response.output_item.added" and getattr(event.item, "type", None) == "function_call":
          in_tool_call = True
          tool_name = event.item.name
          tool_call_id = event.item.call_id
          tool_args_buffer = ""
          self.end_active_block()
          self.active_block = CodeBlock()
          if "function_call" not in self.messages[-1]:
            self.messages[-1]["function_call"] = {"name": tool_name, "arguments": ""}
        elif etype == "response.function_call_arguments.delta":
          tool_args_buffer += event.delta
          if "function_call" not in self.messages[-1]:
            self.messages[-1]["function_call"] = {"name": tool_name or "run_code", "arguments": ""}
          self.messages[-1]["function_call"]["arguments"] = tool_args_buffer
          parsed = parse_partial_json(tool_args_buffer)
          self.messages[-1]["function_call"]["parsed_arguments"] = parsed
          self.active_block.update_from_message(self.messages[-1])
        elif etype == "response.function_call_arguments.done":
          # finalize tool call
          final_args = event.arguments or tool_args_buffer
          try:
            parsed = json.loads(final_args)
          except Exception:
            parsed = parse_partial_json(final_args)
          if "function_call" not in self.messages[-1]:
            self.messages[-1]["function_call"] = {"name": tool_name or "run_code"}
          self.messages[-1]["function_call"]["arguments"] = final_args
          self.messages[-1]["function_call"]["parsed_arguments"] = parsed
          self.messages[-1]["tool_calls"] = [{
            "id": tool_call_id or "tool_call_0",
            "type": "function",
            "function": {"name": tool_name or "run_code", "arguments": final_args}
          }]

          if not self.auto_run:
            self.active_block.end()
            language = self.active_block.language
            code = self.active_block.code
            resp_in = input("  Would you like to run this code? (y/n)\n\n  ")
            print("")
            if resp_in.strip().lower() == "y":
              self.active_block = CodeBlock()
              self.active_block.language = language
              self.active_block.code = code
            else:
              self.active_block.end()
              self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id or "tool_call_0",
                "name": "run_code",
                "content": "User decided not to run this code."
              })
              return

          language = self.messages[-1]["function_call"]["parsed_arguments"]["language"] if self.messages[-1]["function_call"].get("parsed_arguments") else None
          if language not in self.code_emplodes:
            self.code_emplodes[language] = CodeEmplode(language, False)
          code_emplode = self.code_emplodes[language]
          code_emplode.active_block = self.active_block
          code_emplode.run()
          self.active_block.end()
          self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id or "tool_call_0",
            "name": "run_code",
            "content": self.active_block.output if self.active_block.output else "No output"
          })
          self.respond()
          return
        elif etype == "response.completed":
          self.active_block.end()
          return
        elif etype == "response.error":
          self.active_block.end()
          raise Exception(getattr(event, "error", None))

    else:
      # Non-streaming response
      message_text = resp.output_text if hasattr(resp, "output_text") else ""
      tool_item = None
      for item in resp.output:
        if getattr(item, "type", None) == "function_call":
          tool_item = item
          break
      if tool_item is None:
        self.messages.append({"role": "assistant", "content": message_text})
        self.active_block = MessageBlock()
        self.active_block.update_from_message(self.messages[-1])
        self.active_block.end()
        return
      else:
        args = getattr(tool_item, "arguments", "") or ""
        try:
          parsed = json.loads(args) if args else None
        except Exception:
          parsed = parse_partial_json(args)
        self.messages.append({
          "role": "assistant",
          "function_call": {"name": getattr(tool_item, "name", "run_code"), "arguments": args, "parsed_arguments": parsed},
          "tool_calls": [{"id": getattr(tool_item, "id", getattr(tool_item, "call_id", "tool_call_0")), "type": "function", "function": {"name": getattr(tool_item, "name", "run_code"), "arguments": args}}]
        })
        self.active_block = CodeBlock()
        self.active_block.update_from_message(self.messages[-1])
        if not self.auto_run:
          self.active_block.end()
          language = self.active_block.language
          code = self.active_block.code
          resp_in = input("  Would you like to run this code? (y/n)\n\n  ")
          print("")
          if resp_in.strip().lower() == "y":
            self.active_block = CodeBlock()
            self.active_block.language = language
            self.active_block.code = code
          else:
            self.active_block.end()
            self.messages.append({
              "role": "tool",
              "tool_call_id": getattr(tool_item, "id", getattr(tool_item, "call_id", "tool_call_0")),
              "name": "run_code",
              "content": "User decided not to run this code."
            })
            return
        language = self.messages[-1]["function_call"]["parsed_arguments"]["language"] if self.messages[-1]["function_call"].get("parsed_arguments") else None
        if language not in self.code_emplodes:
          self.code_emplodes[language] = CodeEmplode(language, False)
        code_emplode = self.code_emplodes[language]
        code_emplode.active_block = self.active_block
        code_emplode.run()
        self.active_block.end()
        self.messages.append({
          "role": "tool",
          "tool_call_id": getattr(tool_item, "id", getattr(tool_item, "call_id", "tool_call_0")),
          "name": "run_code",
          "content": self.active_block.output if self.active_block.output else "No output"
        })
        self.respond()
        return

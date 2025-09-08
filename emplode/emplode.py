from .message_block import MessageBlock
from .code_block import CodeBlock
from .code_emplode import CodeEmplode

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

  def respond(self):
    messages = self._approx_trim()

    try:
      response = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        tools=[{"type": "function", "function": function_schema}],
        stream=True,
      )
      streaming_mode = True
    except Exception:
      response = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        tools=[{"type": "function", "function": function_schema}],
        stream=False,
      )
      streaming_mode = False

    if streaming_mode:
      self.messages.append({"role": "assistant"})
      in_tool_call = False
      tool_call_id = None
      tool_name = None
      tool_args_buffer = ""
      self.active_block = None

      for chunk in response:
        choice = getattr(chunk, 'choices', [None])[0]
        if not choice:
          continue
        delta = choice.delta
        if delta.content:
          if "content" not in self.messages[-1]:
            self.messages[-1]["content"] = ""
          self.messages[-1]["content"] += delta.content

        if delta.tool_calls:
          for tc in delta.tool_calls:
            if getattr(tc, 'id', None):
              tool_call_id = tc.id
            if tc.function and getattr(tc.function, 'name', None):
              tool_name = tc.function.name
            if tc.function and getattr(tc.function, 'arguments', None):
              tool_args_buffer += tc.function.arguments
          if not in_tool_call:
            self.end_active_block()
            self.active_block = CodeBlock()
            in_tool_call = True
          if "function_call" not in self.messages[-1]:
            self.messages[-1]["function_call"] = {}
          self.messages[-1]["function_call"]["name"] = tool_name or "run_code"
          self.messages[-1]["function_call"]["arguments"] = tool_args_buffer
          try:
            parsed = json.loads(tool_args_buffer) if tool_args_buffer else None
          except Exception:
            parsed = None
          self.messages[-1]["function_call"]["parsed_arguments"] = parsed
          self.messages[-1]["tool_calls"] = [{
            "id": tool_call_id or "tool_call_0",
            "type": "function",
            "function": {"name": tool_name or "run_code", "arguments": tool_args_buffer or ""}
          }]
        else:
          if not in_tool_call and self.active_block is None:
            self.active_block = MessageBlock()

        self.active_block.update_from_message(self.messages[-1])

        if choice.finish_reason:
          if choice.finish_reason == "tool_calls":
            if not self.auto_run:
              self.active_block.end()
              language = self.active_block.language
              code = self.active_block.code
              response_input = input("  Would you like to run this code? (y/n)\n\n  ")
              print("")
              if response_input.strip().lower() == "y":
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

            if "parsed_arguments" not in self.messages[-1].get("function_call", {}):
              self.messages.append({
                "role": "user",
                "content": "Your function call could not be parsed. Please use ONLY the `run_code` function with `language` and `code`."
              })
              self.respond()
              return

            language = self.messages[-1]["function_call"]["parsed_arguments"]["language"]
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
          else:
            if "content" in self.messages[-1]:
              self.messages[-1]["content"] = self.messages[-1]["content"].strip().rstrip("#")
              self.active_block.update_from_message(self.messages[-1])
              time.sleep(0.1)
            self.active_block.end()
            return
    else:
      choice = response.choices[0]
      message = {
        "role": choice.message.role,
        "content": choice.message.content,
      }
      if choice.message.tool_calls:
        tool_call = choice.message.tool_calls[0]
        args = getattr(tool_call.function, 'arguments', '') or ''
        try:
          parsed = json.loads(args) if args else None
        except Exception:
          parsed = None
        message["function_call"] = {
          "name": getattr(tool_call.function, 'name', 'run_code'),
          "arguments": args,
          "parsed_arguments": parsed,
        }
        message["tool_calls"] = [{
          "id": getattr(tool_call, 'id', 'tool_call_0'),
          "type": "function",
          "function": {"name": getattr(tool_call.function, 'name', 'run_code'), "arguments": args}
        }]
      self.messages.append(message)
      if message.get("tool_calls"):
        self.active_block = CodeBlock()
      else:
        self.active_block = MessageBlock()
      self.active_block.update_from_message(self.messages[-1])

      if message.get("tool_calls"):
        if not self.auto_run:
          self.active_block.end()
          language = self.active_block.language
          code = self.active_block.code
          response_input = input("  Would you like to run this code? (y/n)\n\n  ")
          print("")
          if response_input.strip().lower() == "y":
            self.active_block = CodeBlock()
            self.active_block.language = language
            self.active_block.code = code
          else:
            self.active_block.end()
            self.messages.append({
              "role": "tool",
              "tool_call_id": message["tool_calls"][0]["id"],
              "name": "run_code",
              "content": "User decided not to run this code."
            })
            return
        language = message["function_call"]["parsed_arguments"]["language"] if message["function_call"].get("parsed_arguments") else None
        if language not in self.code_emplodes:
          self.code_emplodes[language] = CodeEmplode(language, False)
        code_emplode = self.code_emplodes[language]
        code_emplode.active_block = self.active_block
        code_emplode.run()
        self.active_block.end()
        self.messages.append({
          "role": "tool",
          "tool_call_id": message["tool_calls"][0]["id"],
          "name": "run_code",
          "content": self.active_block.output if self.active_block.output else "No output"
        })
        self.respond()
      else:
        self.active_block.end()
        return

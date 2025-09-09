from .cli import cli
from .utils import merge_deltas, parse_partial_json
from .message_block import MessageBlock
from .code_block import CodeBlock
from .code_emplode import CodeEmplode

import os
import time
import traceback
import json
import platform
import re
from openai import OpenAI
from openai import BadRequestError
import getpass
import readline
import tokentrim as tt
from rich import print
from rich.markdown import Markdown
from rich.rule import Rule

# Responses API tool definition for function-calling (strict JSON Schema)
RUN_CODE_TOOL = {
  "type": "function",
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
    "required": ["language", "code"],
    "additionalProperties": False
  }
}

missing_api_key_message = "> OpenAI API key not found. Provide an OpenAI API key to continue.\n"

confirm_mode_message = """
Emplode will require approval before running code. Use `emplode -y` to bypass this.
"""


class Emplode:

  def __init__(self):
    self.messages = []
    self.api_key = None
    self.auto_run = False
    self.model = "gpt-5"
    self.debug_mode = False
    self.context_window = 200000
    self.max_tokens = 750
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, 'system_message.txt'), 'r') as f:
      self.system_message = f.read().strip()

    self.code_emplodes = {}
    self.active_block = None
    self.client = None

  def cli(self):
    cli(self)

  def get_info_for_system_message(self):
    username = getpass.getuser()
    cwd = os.getcwd()
    os_name = platform.system()
    return f"[User Info]\nName: {username}\nCWD: {cwd}\nOS: {os_name}"

  def reset(self):
    self.messages = []
    self.code_emplodes = {}

  def load(self, messages):
    self.messages = messages

  def handle_undo(self, arguments):
    if len(self.messages) == 0:
      return
    last_user_index = None
    for i, message in enumerate(self.messages):
      if message.get('role') == 'user':
        last_user_index = i
    removed = []
    if last_user_index is not None:
      removed = self.messages[last_user_index:]
      self.messages = self.messages[:last_user_index]
    print("")
    for m in removed:
      if 'content' in m and m['content'] is not None:
        print(Markdown(f"**Removed message:** `\"{m['content'][:30]}...\"`"))
      elif 'function_call' in m:
        print(Markdown("**Removed codeblock**"))
    print("")

  def handle_help(self, arguments):
    items = {
      "%debug [true/false]": "Toggle debug mode.",
      "%reset": "Reset the current session.",
      "%undo": "Remove the previous user message and response.",
      "%save_message [path]": "Save messages to JSON.",
      "%load_message [path]": "Load messages from JSON.",
      "%help": "Show this help message.",
    }
    base = ["> **Available Commands:**\n\n"]
    for cmd, desc in items.items():
      base.append(f"- `{cmd}`: {desc}\n")
    print(Markdown("".join(base)))

  def handle_debug(self, arguments=None):
    if arguments == "" or arguments == "true":
      print(Markdown("> Entered debug mode"))
      print(self.messages)
      self.debug_mode = True
    elif arguments == "false":
      print(Markdown("> Exited debug mode"))
      self.debug_mode = False
    else:
      print(Markdown("> Unknown argument to debug command."))

  def handle_reset(self, arguments):
    self.reset()
    print(Markdown("> Reset Done"))

  def default_handle(self, arguments):
    print(Markdown("> Unknown command"))
    self.handle_help(arguments)

  def handle_save_message(self, json_path):
    if json_path == "":
      json_path = "messages.json"
    if not json_path.endswith(".json"):
      json_path += ".json"
    with open(json_path, 'w') as f:
      json.dump(self.messages, f, indent=2)
    print(Markdown(f"> messages json export to {os.path.abspath(json_path)}"))

  def handle_load_message(self, json_path):
    if json_path == "":
      json_path = "messages.json"
    if not json_path.endswith(".json"):
      json_path += ".json"
    with open(json_path, 'r') as f:
      self.load(json.load(f))
    print(Markdown(f"> messages json loaded from {os.path.abspath(json_path)}"))

  def handle_command(self, user_input):
    switch = {
      "help": self.handle_help,
      "debug": self.handle_debug,
      "reset": self.handle_reset,
      "save_message": self.handle_save_message,
      "load_message": self.handle_load_message,
      "undo": self.handle_undo,
    }
    user_input = user_input[1:].strip()
    command = user_input.split(" ")[0]
    arguments = user_input[len(command):].strip()
    switch.get(command, self.default_handle)(arguments)

  def chat(self, message=None, return_messages=False):
    self.verify_api_key()

    welcome = ""
    if self.debug_mode:
      welcome += "> Entered debug mode"
    welcome += f"\n> Model set to `{self.model.upper()}`"
    if not self.auto_run:
      welcome += f"\n\n{confirm_mode_message}"
    welcome = welcome.strip()
    if welcome:
      print(Markdown(welcome), '')

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
        if user_input.startswith("%") or user_input.startswith("/"):
          self.handle_command(user_input)
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
      key = os.environ.get('OPENAI_API_KEY')
      if not key:
        print(Markdown(missing_api_key_message))
        key = input("OpenAI API key: ").strip()
        if not key:
          raise Exception("OpenAI API key is required to use Emplode with GPT-5.")
      self.api_key = key
    if self.client is None:
      self.client = OpenAI(api_key=self.api_key)

  def end_active_block(self):
    if self.active_block:
      self.active_block.end()
      self.active_block = None

  def _extract_last_code_block(self, text):
    pattern = re.compile(r"```([a-zA-Z]+)?\n([\s\S]*?)```", re.DOTALL)
    matches = list(pattern.finditer(text or ""))
    if not matches:
      return None, None
    lang = matches[-1].group(1) or "python"
    code = matches[-1].group(2) or ""
    if lang == "bash":
      lang = "shell"
    return lang, code.strip()

  def _stream_with_responses(self, sys_and_messages):
    content_buf = ""
    tool_name = None
    tool_args_buf = ""

    # Live stream
    try:
      with self.client.responses.stream(
        model=self.model,
        input=sys_and_messages,
        tools=[RUN_CODE_TOOL],
      ) as stream:
        for event in stream:
          t = getattr(event, 'type', '')
          # Text deltas
          if 'output_text.delta' in t:
            delta = getattr(event, 'delta', '') or getattr(event, 'text', '')
            if delta:
              content_buf += delta
              if not isinstance(self.active_block, MessageBlock):
                self.end_active_block()
                self.active_block = MessageBlock()
              self.active_block.update_from_message({"content": content_buf})
          # Tool call incremental pieces
          elif 'tool_call.delta' in t:
            d = getattr(event, 'delta', None)
            if isinstance(d, dict):
              if not tool_name and d.get('name'):
                tool_name = d['name']
              if d.get('arguments'):
                tool_args_buf += d['arguments']
            elif isinstance(d, str):
              tool_args_buf += d
          # Tool call finished
          elif 'tool_call.completed' in t:
            self._execute_run_code(tool_name, tool_args_buf)
            return
          # Response finished
          elif t.endswith('completed') or t == 'response.completed':
            # If model wrote a code block instead of tool call, run it
            lang, code = self._extract_last_code_block(content_buf)
            if lang and code:
              self._execute_run_code('run_code', json.dumps({"language": lang, "code": code}))
            return
        _ = stream.get_final_response()
    except BadRequestError:
      # Fallback to non-stream
      r = self.client.responses.create(
        model=self.model,
        input=sys_and_messages,
        tools=[RUN_CODE_TOOL],
        stream=False,
      )
      return self._handle_nonstream_response(r)

  def _handle_nonstream_response(self, r):
    # Try to read tool calls; structure can vary by SDK version
    try:
      out = getattr(r, 'output', None) or []
    except Exception:
      out = []
    # Search for tool call
    tool_name = None
    tool_args = None
    text_accum = ""
    for item in out:
      t = getattr(item, 'type', None)
      if t == 'tool_call':
        f = getattr(item, 'tool_call', None)
        if f and getattr(f, 'type', '') == 'function':
          tool_name = getattr(f, 'name', None)
          tool_args = getattr(f, 'arguments', None)
          break
      if t == 'message' and hasattr(item, 'content'):
        for c in getattr(item, 'content', []) or []:
          if getattr(c, 'type', None) == 'output_text':
            text_accum += getattr(c, 'text', '') or ''
    if tool_name:
      self._execute_run_code(tool_name, tool_args or "")
      return
    if text_accum:
      # Try to run code fence if present
      lang, code = self._extract_last_code_block(text_accum)
      if lang and code:
        self._execute_run_code('run_code', json.dumps({"language": lang, "code": code}))
        return
      self.end_active_block()
      self.active_block = MessageBlock()
      self.active_block.update_from_message({"content": text_accum})
      self.active_block.end()

  def _execute_run_code(self, tool_name, raw_args):
    if tool_name != 'run_code':
      return
    parsed = parse_partial_json(raw_args or "") or {}
    language = parsed.get('language')
    code = parsed.get('code')
    if not language or not code:
      self.end_active_block()
      self.active_block = MessageBlock()
      self.active_block.update_from_message({"content": "Tool arguments missing 'language' or 'code'."})
      self.active_block.end()
      return
    # Show code
    self.end_active_block()
    print()
    self.active_block = CodeBlock()
    self.active_block.language = language
    self.active_block.code = code
    self.active_block.refresh()
    if self.auto_run is False:
      self.active_block.end()
      resp = input("  Would you like to run this code? (y/n)\n\n  ")
      print("")
      if resp.strip().lower() != 'y':
        return
      self.active_block = CodeBlock()
      self.active_block.language = language
      self.active_block.code = code
    if language not in self.code_emplodes:
      self.code_emplodes[language] = CodeEmplode(language, self.debug_mode)
    ce = self.code_emplodes[language]
    ce.active_block = self.active_block
    ce.run()
    self.active_block.end()

  def respond(self):
    info = self.get_info_for_system_message()
    system_message = self.system_message + "\n\n" + info

    # Trim conversation to fit
    trimmed = tt.trim(self.messages, max_tokens=(self.context_window - self.max_tokens - 25), system_message=system_message)

    # Convert to Responses API input
    sys_and_messages = [{"role": "system", "content": system_message}] + trimmed[1:]

    # Stream first; fallback to non-stream automatically
    self._stream_with_responses(sys_and_messages)

  def _print_welcome_message(self):
    print("", "", Markdown(f"\nWelcome to **Emplode**.\n"), "")

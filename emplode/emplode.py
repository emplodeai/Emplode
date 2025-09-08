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
from openai import OpenAI
from openai import BadRequestError
import getpass
import readline
import tokentrim as tt
from rich import print
from rich.markdown import Markdown
from rich.rule import Rule

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

missing_api_key_message = "> OpenAI API key not found\n\nTo use `GPT-5` please provide an OpenAI API key.\n"

confirm_mode_message = """
**Emplode** will require approval before running code. Use `emplode -y` to bypass this.

Press `CTRL-C` to exit.
"""


class Emplode:

  def __init__(self):
    self.messages = []
    self.temperature = 1.0
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

    info = ""

    username = getpass.getuser()
    current_working_directory = os.getcwd()
    operating_system = platform.system()

    info += f"[User Info]\nName: {username}\nCWD: {current_working_directory}\nOS: {operating_system}"

    return info

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

    removed_messages = []

    if last_user_index is not None:
        removed_messages = self.messages[last_user_index:]
        self.messages = self.messages[:last_user_index]

    print("") 

    for message in removed_messages:
      if 'content' in message and message['content'] != None:
        print(Markdown(f"**Removed message:** `\"{message['content'][:30]}...\"`"))
      elif 'function_call' in message:
        print(Markdown(f"**Removed codeblock**"))
    
    print("") 
  def handle_help(self, arguments):
    commands_description = {
      "%debug [true/false]": "Toggle debug mode. Without arguments or with 'true', it enters debug mode. With 'false', it exits debug mode.",
      "%reset": "Resets the current session.",
      "%undo": "Remove previous messages and its response from the message history.",
      "%save_message [path]": "Saves messages to a specified JSON path. If no path is provided, it defaults to 'messages.json'.",
      "%load_message [path]": "Loads messages from a specified JSON path. If no path is provided, it defaults to 'messages.json'.",
      "%help": "Show this help message.",
    }

    base_message = [
      "> **Available Commands:**\n\n"
    ]

    for cmd, desc in commands_description.items():
      base_message.append(f"- `{cmd}`: {desc}\n")

    print(Markdown("".join(base_message)))


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
    action = switch.get(command,
                        self.default_handle)  
    action(arguments)  

  def chat(self, message=None, return_messages=False):

    self.verify_api_key()

    welcome_message = ""

    if self.debug_mode:
      welcome_message += "> Entered debug mode"

    if not self.auto_run:
      notice_model = f"{self.model.upper()}"
      welcome_message += f"\n> Model set to `{notice_model}`\n\n**Tip:** To auto-run code, use `emplode -y`"
    
    if not self.auto_run:
      welcome_message += "\n\n" + confirm_mode_message

    welcome_message = welcome_message.strip()

    if welcome_message != "":
      if welcome_message.startswith(">"):
        print(Markdown(welcome_message), '')
      else:
        print('', Markdown(welcome_message), '')

    if message:
      self.messages.append({"role": "user", "content": message})
      self.respond()

    else:
      while True:
        try:
          user_input = input("> ").strip()
        except EOFError:
          break
        except KeyboardInterrupt:
          print()  
          break

        readline.add_history(user_input)

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
      if 'OPENAI_API_KEY' in os.environ:
        self.api_key = os.environ['OPENAI_API_KEY']
      else:
        self._print_welcome_message()
        time.sleep(1)

        print(Rule(style="white"))

        print(Markdown(missing_api_key_message), '', Rule(style="white"), '')
        response = input("OpenAI API key: ")

        if response == "":
          raise Exception("OpenAI API key is required to use Emplode with GPT-5.")
        else:
          self.api_key = response
          print('', Markdown("**Tip:** To save this key for later, run `setx OPENAI_API_KEY your_api_key` on Windows or `export OPENAI_API_KEY=your_api_key` on Mac/Linux."), '')
          time.sleep(2)
          print(Rule(style="white"))

    if self.client is None:
      self.client = OpenAI(api_key=self.api_key)

  def end_active_block(self):
    if self.active_block:
      self.active_block.end()
      self.active_block = None

  def respond(self):
    info = self.get_info_for_system_message()
    system_message = self.system_message + "\n\n" + info

    messages = tt.trim(self.messages, max_tokens=(self.context_window-self.max_tokens-25), system_message=system_message)

    if self.debug_mode:
      print("\n", "Sending `messages` to LLM:", "\n")
      print(messages)
      print()

    # Prefer non-streaming for GPT-5 and use tools API
    try:
      r = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        tools=[{"type": "function", "function": function_schema}],
        stream=False,
      )
    except BadRequestError as e:
      # If tools are not supported, fall back to no tools
      if self.debug_mode:
        traceback.print_exc()
      r = self.client.chat.completions.create(
        model=self.model,
        messages=messages,
        stream=False,
      )

    choice = r.choices[0]
    msg = choice.message

    # Build a synthetic assistant message for our transcript
    assistant_msg = {"role": "assistant"}

    # Handle tool calls (function calling)
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
      fn = tool_calls[0].function
      arguments = fn.arguments or ""
      assistant_msg["function_call"] = {"name": fn.name, "arguments": arguments}
      self.messages.append(assistant_msg)

      # Parse arguments safely
      parsed = parse_partial_json(arguments) or {}
      language = parsed.get("language")
      code = parsed.get("code")
      if not language or not code:
        self.active_block = MessageBlock()
        self.active_block.update_from_message({"content": "Your function call could not be parsed. It must include JSON with 'language' and 'code'."})
        self.active_block.end()
        return

      # Show code block
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
        if resp.strip().lower() != "y":
          return
        self.active_block = CodeBlock()
        self.active_block.language = language
        self.active_block.code = code

      # Execute
      if language not in self.code_emplodes:
        self.code_emplodes[language] = CodeEmplode(language, self.debug_mode)
      code_emplode = self.code_emplodes[language]
      code_emplode.active_block = self.active_block
      code_emplode.run()
      self.active_block.end()
      return

    # Otherwise, plain assistant content
    content = msg.content or ""
    assistant_msg["content"] = content
    self.messages.append(assistant_msg)

    self.end_active_block()
    self.active_block = MessageBlock()
    self.active_block.update_from_message({"content": content})
    self.active_block.end()
    return

  def _print_welcome_message(self):
    print("", "", Markdown(f"\nWelcome to **Emplode**.\n"), "")

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
import getpass
import requests
import readline
import tokentrim as tt
from rich import print
from rich.markdown import Markdown
from rich.rule import Rule

function_schema = {
  "name": "run_code",
  "description":
  "Executes code on the user's machine and returns the output",
  "parameters": {
    "type": "object",
    "properties": {
      "language": {
        "type": "string",
        "description":
        "The programming language",
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
    self.temperature = 0.001
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

    query = []
    for message in self.messages[-2:]:
      message_for_semantic_search = {"role": message.get("role", "assistant")}
      if "content" in message:
        message_for_semantic_search["content"] = message["content"]
      if "function_call" in message and "parsed_arguments" in message["function_call"]:
        message_for_semantic_search["function_call"] = message["function_call"]["parsed_arguments"]
      query.append(message_for_semantic_search)

    url = "https://open-procedures.replit.app/search/"

    try:
      relevant_procedures = requests.get(url, data=json.dumps(query)).json().get("procedures", [])
      if relevant_procedures:
        info += "\n\n# Recommended Procedures\n" + "\n---\n".join(relevant_procedures) + "\nIn your plan, include steps and, if present, **EXACT CODE SNIPPETS** (especially for depracation notices, **WRITE THEM INTO YOUR PLAN -- underneath each numbered step** as they will VANISH once you execute your first line of code, so WRITE THEM DOWN NOW if you need them) from the above procedures if they are relevant to the task. Again, include **VERBATIM CODE SNIPPETS** from the procedures above if they are relevent to the task **directly in your plan.**"
    except:
      pass

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

    additional_info = [
      "\n\nFor further assistance, please join our community Discord or consider contributing to the project's development."
    ]

    full_message = base_message + additional_info

    print(Markdown("".join(full_message)))


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

    error = ""

    for _ in range(3): 
      try:
        response = self.client.chat.completions.create(
          model=self.model,
          messages=messages,
          functions=[function_schema],
          temperature=self.temperature,
          stream=True,
        )
        break
      except:
        if self.debug_mode:
          traceback.print_exc()
        error = traceback.format_exc()
        time.sleep(3)
    else:
      raise Exception(error)

    self.messages.append({})
    in_function_call = False
    self.active_block = None

    for chunk in response:
      try:
        chunk_dict = chunk.model_dump()
      except Exception:
        chunk_dict = chunk

      delta = chunk_dict.get("choices", [{}])[0].get("delta", {})
      finish_reason = chunk_dict.get("choices", [{}])[0].get("finish_reason")

      self.messages[-1] = merge_deltas(self.messages[-1], delta)

      condition = "function_call" in self.messages[-1]

      if condition:
        if in_function_call == False:

          self.end_active_block()

          last_role = self.messages[-2]["role"]
          if last_role == "user" or last_role == "function":
            print()

          self.active_block = CodeBlock()

        in_function_call = True

        if "arguments" in self.messages[-1]["function_call"]:
          arguments = self.messages[-1]["function_call"]["arguments"]
          new_parsed_arguments = parse_partial_json(arguments)
          if new_parsed_arguments:
            self.messages[-1]["function_call"][
              "parsed_arguments"] = new_parsed_arguments

      else:
        if in_function_call == True:
          in_function_call = False

        if self.active_block == None:
          self.active_block = MessageBlock()

      self.active_block.update_from_message(self.messages[-1])

      if finish_reason:
        if finish_reason == "function_call":

          if self.debug_mode:
            print("Running function:")
            print(self.messages[-1])
            print("---")

          if self.auto_run == False:

            self.active_block.end()
            language = self.active_block.language
            code = self.active_block.code

            response = input("  Would you like to run this code? (y/n)\n\n  ")
            print("")

            if response.strip().lower() == "y":
              self.active_block = CodeBlock()
              self.active_block.language = language
              self.active_block.code = code

            else:
              self.active_block.end()
              self.messages.append({
                "role":
                "function",
                "name":
                "run_code",
                "content":
                "User decided not to run this code."
              })
              return

          if "parsed_arguments" not in self.messages[-1]["function_call"]:

            self.messages.append({
              "role": "function",
              "name": "run_code",
              "content": """Your function call could not be parsed. Please use ONLY the `run_code` function, which takes two parameters: `code` and `language`. Your response should be formatted as a JSON."""
            })

            self.respond()
            return

          language = self.messages[-1]["function_call"]["parsed_arguments"][
            "language"]
          if language not in self.code_emplodes:
            self.code_emplodes[language] = CodeEmplode(language, self.debug_mode)
          code_emplode = self.code_emplodes[language]

          code_emplode.active_block = self.active_block
          code_emplode.run()

          self.active_block.end()

          self.messages.append({
            "role": "function",
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

  def _print_welcome_message(self):
    print("", "", Markdown(f"\nWelcome to **Emplode**.\n"), "")

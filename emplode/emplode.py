from .cli import cli
from .utils import merge_deltas, parse_partial_json
from .message_block import MessageBlock
from .code_block import CodeBlock
from .code_emplode import CodeEmplode
from .get_hf_llm import get_hf_llm

import os
import time
import traceback
import json
import platform
import openai
import litellm
import pkg_resources

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

missing_api_key_message = """> OpenAI API key not found

To use `GPT-4o` (recommended) please provide an OpenAI API key.

To use `Code-Llama` (free but less capable) press `enter`.
"""

missing_azure_info_message = """> Azure OpenAI Service API info not found

To use `GPT-4` (recommended) please provide an Azure OpenAI API key, a API base, a deployment name and a API version.

To use `Code-Llama` (free but less capable) press `enter`.
"""

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
    self.local = False
    self.model = "gpt-4o"
    self.debug_mode = False
    self.api_base = None 
    self.context_window = 2000 
    self.max_tokens = 750
    self.use_azure = False
    self.azure_api_base = None
    self.azure_api_version = None
    self.azure_deployment_name = None
    self.azure_api_type = "azure"
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, 'system_message.txt'), 'r') as f:
      self.system_message = f.read().strip()

    self.code_emplodes = {}

    self.active_block = None

    self.llama_instance = None

  def cli(self):
    cli(self)

  def get_info_for_system_message(self):

    info = ""

    username = getpass.getuser()
    current_working_directory = os.getcwd()
    operating_system = platform.system()

    info += f"[User Info]\nName: {username}\nCWD: {current_working_directory}\nOS: {operating_system}"

    if not self.local:

      query = []
      for message in self.messages[-2:]:
        message_for_semantic_search = {"role": message["role"]}
        if "content" in message:
          message_for_semantic_search["content"] = message["content"]
        if "function_call" in message and "parsed_arguments" in message["function_call"]:
          message_for_semantic_search["function_call"] = message["function_call"]["parsed_arguments"]
        query.append(message_for_semantic_search)

      url = "https://open-procedures.replit.app/search/"

      try:
        relevant_procedures = requests.get(url, data=json.dumps(query)).json()["procedures"]
        info += "\n\n# Recommended Procedures\n" + "\n---\n".join(relevant_procedures) + "\nIn your plan, include steps and, if present, **EXACT CODE SNIPPETS** (especially for depracation notices, **WRITE THEM INTO YOUR PLAN -- underneath each numbered step** as they will VANISH once you execute your first line of code, so WRITE THEM DOWN NOW if you need them) from the above procedures if they are relevant to the task. Again, include **VERBATIM CODE SNIPPETS** from the procedures above if they are relevent to the task **directly in your plan.**"
      except:
        pass

    elif self.local:
      info += "\n\nTo run code, write a fenced code block (i.e ```python, R or ```shell) in markdown. When you close it with ```, it will be run. You'll then be given its output."
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
        print(Markdown(f"**Removed codeblock**")) # TODO: Could add preview of code removed here.
    
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

    if not self.local:
      self.verify_api_key()

    if self.local:

      if self.llama_instance == None:
        try:
          self.llama_instance = get_hf_llm(self.model, self.debug_mode, self.context_window)
          if self.llama_instance == None:
            return
        except:
          traceback.print_exc()

          print(Markdown("".join([
            f"> Failed to install `{self.model}`.",
            f"\n\n**Common Fixes:** You can follow our simple setup docs at the link below to resolve common errors.\n\n```\nhttps://github.com/emplodeai/emplode/\n```",
            f"\n\n**If you've tried that and you're still getting an error, we have likely not built the proper `{self.model}` support for your system.**",
            "\n\n*( Running language models locally is a difficult task!* If you have insight into the best way to implement this across platforms/architectures, please join the Emplode community Discord and consider contributing the project's development. )",
            "\n\nPress enter to switch to `GPT-4o` (recommended)."
          ])))
          input()

          self.local = False
          self.model = "gpt-4o"
          self.verify_api_key()

    welcome_message = ""

    if self.debug_mode:
      welcome_message += "> Entered debug mode"

    if not self.local and not self.auto_run:

      if self.use_azure:
        notice_model = f"{self.azure_deployment_name} (Azure)"
      else:
        notice_model = f"{self.model.upper()}"
      welcome_message += f"\n> Model set to `{notice_model}`\n\n**Tip:** To run locally, use `emplode --local`"
      
    if self.local:
      welcome_message += f"\n> Model set to `{self.model}`"

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
    if self.use_azure:
      all_env_available = (
        ('AZURE_API_KEY' in os.environ or 'OPENAI_API_KEY' in os.environ) and
        'AZURE_API_BASE' in os.environ and
        'AZURE_API_VERSION' in os.environ and
        'AZURE_DEPLOYMENT_NAME' in os.environ)
      if all_env_available:
        self.api_key = os.environ.get('AZURE_API_KEY') or os.environ['OPENAI_API_KEY']
        self.azure_api_base = os.environ['AZURE_API_BASE']
        self.azure_api_version = os.environ['AZURE_API_VERSION']
        self.azure_deployment_name = os.environ['AZURE_DEPLOYMENT_NAME']
        self.azure_api_type = os.environ.get('AZURE_API_TYPE', 'azure')
      else:
        self._print_welcome_message()
        time.sleep(1)

        print(Rule(style="white"))

        print(Markdown(missing_azure_info_message), '', Rule(style="white"), '')
        response = input("Azure OpenAI API key: ")

        if response == "":

          print(Markdown(
            "> Switching to `Code-Llama`...\n\n**Tip:** Run `emplode --local` to automatically use `Code-Llama`."),
                '')
          time.sleep(2)
          print(Rule(style="white"))

          import inquirer

          print('', Markdown("**Emplode** will use `Code Llama` for local execution."), '')

          models = {
              '7B': 'TheBloke/CodeLlama-7B-Instruct-GGUF',
              '13B': 'TheBloke/CodeLlama-13B-Instruct-GGUF',
              '34B': 'TheBloke/CodeLlama-34B-Instruct-GGUF'
          }

          parameter_choices = list(models.keys())
          questions = [inquirer.List('param', message="Parameter count (smaller is faster, larger is more capable)", choices=parameter_choices)]
          answers = inquirer.prompt(questions)
          chosen_param = answers['param']

          self.model = models[chosen_param]
          self.local = True




          return

        else:
          self.api_key = response
          self.azure_api_base = input("Azure OpenAI API base: ")
          self.azure_deployment_name = input("Azure OpenAI deployment name of GPT: ")
          self.azure_api_version = input("Azure OpenAI API version: ")
          print('', Markdown(
            "**Tip:** To save this key for later, run `export AZURE_API_KEY=your_api_key AZURE_API_BASE=your_api_base AZURE_API_VERSION=your_api_version AZURE_DEPLOYMENT_NAME=your_gpt_deployment_name` on Mac/Linux or `setx AZURE_API_KEY your_api_key AZURE_API_BASE your_api_base AZURE_API_VERSION your_api_version AZURE_DEPLOYMENT_NAME your_gpt_deployment_name` on Windows."),
                '')
          time.sleep(2)
          print(Rule(style="white"))

      litellm.api_type = self.azure_api_type
      litellm.api_base = self.azure_api_base
      litellm.api_version = self.azure_api_version
      litellm.api_key = self.api_key
    else:
      if self.api_key == None:
        if 'OPENAI_API_KEY' in os.environ:
          self.api_key = os.environ['OPENAI_API_KEY']
        else:
          self._print_welcome_message()
          time.sleep(1)

          print(Rule(style="white"))

          print(Markdown(missing_api_key_message), '', Rule(style="white"), '')
          response = input("OpenAI API key: ")

          if response == "":

              print(Markdown(
                "> Switching to `Code-Llama`...\n\n**Tip:** Run `emplode --local` to automatically use `Code-Llama`."),
                    '')
              time.sleep(2)
              print(Rule(style="white"))

              import inquirer

              print('', Markdown("**Emplode** will use `Code Llama` for local execution."), '')

              models = {
                  '7B': 'TheBloke/CodeLlama-7B-Instruct-GGUF',
                  '13B': 'TheBloke/CodeLlama-13B-Instruct-GGUF',
                  '34B': 'TheBloke/CodeLlama-34B-Instruct-GGUF'
              }

              parameter_choices = list(models.keys())
              questions = [inquirer.List('param', message="Parameter count (smaller is faster, larger is more capable)", choices=parameter_choices)]
              answers = inquirer.prompt(questions)
              chosen_param = answers['param']
              self.model = models[chosen_param]
              self.local = True




              return

          else:
              self.api_key = response
              print('', Markdown("**Tip:** To save this key for later, run `setx OPENAI_API_KEY your_api_key` on Windows or `export OPENAI_API_KEY=your_api_key` on Mac/Linux."), '')
              time.sleep(2)
              print(Rule(style="white"))

      litellm.api_key = self.api_key
      if self.api_base:
        litellm.api_base = self.api_base

  def end_active_block(self):
    if self.active_block:
      self.active_block.end()
      self.active_block = None

  def respond(self):
    info = self.get_info_for_system_message()

    if self.local:
      self.system_message = "\n".join(self.system_message.split("\n")[:2])
      self.system_message += "\nOnly do what the user asks you to do, then ask what they'd like to do next."

    system_message = self.system_message + "\n\n" + info

    if self.local:
      messages = tt.trim(self.messages, max_tokens=(self.context_window-self.max_tokens-25), system_message=system_message)
    else:
      messages = tt.trim(self.messages, self.model, system_message=system_message)

    if self.debug_mode:
      print("\n", "Sending `messages` to LLM:", "\n")
      print(messages)
      print()

    if not self.local:
      
      error = ""
      
      for _ in range(3): 
        try:

            if self.use_azure:
              response = litellm.completion(
                  f"azure/{self.azure_deployment_name}",
                  messages=messages,
                  functions=[function_schema],
                  temperature=self.temperature,
                  stream=True,
                  )
            else:
              if self.api_base:
                response = litellm.completion(
                  api_base=self.api_base,
                  model = "custom/" + self.model,
                  messages=messages,
                  functions=[function_schema],
                  stream=True,
                  temperature=self.temperature,
                )
              else:
                response = litellm.completion(
                  model=self.model,
                  messages=messages,
                  functions=[function_schema],
                  stream=True,
                  temperature=self.temperature,
                )

            break
        except:
            if self.debug_mode:
              traceback.print_exc()
            error = traceback.format_exc()
            time.sleep(3)
      else:
        raise Exception(error)
            
    elif self.local:

      def messages_to_prompt(messages):


        for message in messages:
          if "role" not in message:
            message["role"] = "assistant"

        if "falcon" in self.model.lower():

          formatted_messages = ""
          for message in messages:
            formatted_messages += f"{message['role'].capitalize()}: {message['content']}\n"
          formatted_messages = formatted_messages.strip()

        else:
          
          system_prompt = messages[0]['content']
          formatted_messages = f"<s>[INST] <<SYS>>\n{system_prompt}\n<</SYS>>\n"

          for index, item in enumerate(messages[1:]):
              role = item['role']
              content = item['content']

              if role == 'user':
                  formatted_messages += f"{content} [/INST] "
              elif role == 'function':
                  formatted_messages += f"Output: {content} [/INST] "
              elif role == 'assistant':
                  formatted_messages += f"{content} </s><s>[INST] "

          if formatted_messages.endswith("<s>[INST] "):
              formatted_messages = formatted_messages[:-10]

        return formatted_messages

      prompt = messages_to_prompt(messages)
      if messages[-1]["role"] != "function":
        prompt += "Let's explore this. By the way, I can run code on your machine by writing the code in a markdown code block. This works for shell, javascript, python, R, and applescript. I'm going to try to do this for your task. Anyway, "
      elif messages[-1]["role"] == "function" and messages[-1]["content"] != "No output":
        prompt += "Given the output of the code I just ran, "
      elif messages[-1]["role"] == "function" and messages[-1]["content"] == "No output":
        prompt += "Given the fact that the code I just ran produced no output, "


      if self.debug_mode:
        import builtins
        builtins.print("TEXT PROMPT SEND TO LLM:\n", prompt)

      response = self.llama_instance(
        prompt,
        stream=True,
        temperature=self.temperature,
        stop=["</s>"],
        max_tokens=750 
      )

    self.messages.append({})
    in_function_call = False
    llama_function_call_finished = False
    self.active_block = None

    for chunk in response:
      if self.use_azure and ('choices' not in chunk or len(chunk['choices']) == 0):
        continue

      if self.local:
        if "content" not in messages[-1]:
          chunk["choices"][0]["text"] = chunk["choices"][0]["text"].capitalize()
          messages[-1]["role"] = "assistant"
        delta = {"content": chunk["choices"][0]["text"]}
      else:
        delta = chunk["choices"][0]["delta"]

      self.messages[-1] = merge_deltas(self.messages[-1], delta)

      if not self.local:
        condition = "function_call" in self.messages[-1]
      elif self.local:
        if "content" in self.messages[-1]:
          condition = self.messages[-1]["content"].count("```") % 2 == 1
        else:
          condition = False

      if condition:
        if in_function_call == False:

          self.end_active_block()

          last_role = self.messages[-2]["role"]
          if last_role == "user" or last_role == "function":
            print()

          self.active_block = CodeBlock()

        in_function_call = True

        if not self.local:
          if "arguments" in self.messages[-1]["function_call"]:
            arguments = self.messages[-1]["function_call"]["arguments"]
            new_parsed_arguments = parse_partial_json(arguments)
            if new_parsed_arguments:
              self.messages[-1]["function_call"][
                "parsed_arguments"] = new_parsed_arguments

        elif self.local:
          if "content" in self.messages[-1]:

            content = self.messages[-1]["content"]

            if "```" in content:
              blocks = content.split("```")

              current_code_block = blocks[-1]

              lines = current_code_block.split("\n")

              if content.strip() == "```": 
                language = None
              else:
                if lines[0] != "":
                  language = lines[0].strip()
                else:
                  language = "python"
                  if len(lines) > 1:
                    if lines[1].startswith("pip"):
                      language = "shell"

              code = '\n'.join(lines[1:]).strip("` \n")

              arguments = {"code": code}
              if language: 
                if language == "bash":
                  language = "shell"
                arguments["language"] = language

            if "function_call" not in self.messages[-1]:
              self.messages[-1]["function_call"] = {}

            self.messages[-1]["function_call"]["parsed_arguments"] = arguments

      else:
        if in_function_call == True:

          if self.local:
          
            llama_function_call_finished = True

        in_function_call = False

        if self.active_block == None:

          self.active_block = MessageBlock()

      self.active_block.update_from_message(self.messages[-1])

      if chunk["choices"][0]["finish_reason"] or llama_function_call_finished:
        if chunk["choices"][
            0]["finish_reason"] == "function_call" or llama_function_call_finished:

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

          if not self.local and "parsed_arguments" not in self.messages[-1]["function_call"]:

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

        if chunk["choices"][0]["finish_reason"] != "function_call":

          if self.local and "content" in self.messages[-1]:
            self.messages[-1]["content"] = self.messages[-1]["content"].strip().rstrip("#")
            self.active_block.update_from_message(self.messages[-1])
            time.sleep(0.1)

          self.active_block.end()
          return

  def _print_welcome_message(self):
    print("", "", Markdown(f"\nWelcome to **Emplode**.\n"), "")

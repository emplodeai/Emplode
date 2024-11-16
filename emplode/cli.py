import argparse
import os
from dotenv import load_dotenv
import requests
from packaging import version
import pkg_resources
from rich import print as rprint
from rich.markdown import Markdown
import inquirer

load_dotenv()

def check_for_update():
    response = requests.get(f'https://pypi.org/pypi/emplode/json')
    latest_version = response.json()['info']['version']

    current_version = pkg_resources.get_distribution("emplode").version

    return version.parse(latest_version) > version.parse(current_version)

def cli(emplode):

  try:
    if check_for_update():
      print("A new version is available. Please run 'pip install --upgrade emplode'.")
  except:
    pass

  AUTO_RUN = os.getenv('EMPLODE_CLI_AUTO_RUN', 'False') == 'True'
  FAST_MODE = os.getenv('EMPLODE_CLI_FAST_MODE', 'False') == 'True'
  LOCAL_RUN = os.getenv('EMPLODE_CLI_LOCAL_RUN', 'False') == 'True'
  DEBUG = os.getenv('EMPLODE_CLI_DEBUG', 'False') == 'True'
  USE_AZURE = os.getenv('EMPLODE_CLI_USE_AZURE', 'False') == 'True'

  parser = argparse.ArgumentParser(description='Command Emplode.')
  
  parser.add_argument('-y',
                      '--yes',
                      action='store_true',
                      default=AUTO_RUN,
                      help='execute code without user confirmation')
  parser.add_argument('-f',
                      '--fast',
                      action='store_true',
                      default=FAST_MODE,
                      help='use gpt-4o-mini instead of gpt-4o')
  parser.add_argument('-l',
                      '--local',
                      action='store_true',
                      default=LOCAL_RUN,
                      help='run fully local with code-llama')
  parser.add_argument(
                      '--falcon',
                      action='store_true',
                      default=False,
                      help='run fully local with falcon-40b')
  parser.add_argument('-d',
                      '--debug',
                      action='store_true',
                      default=DEBUG,
                      help='prints extra information')
  
  parser.add_argument('--model',
                      type=str,
                      help='model name (for OpenAI compatible APIs) or HuggingFace repo',
                      default="",
                      required=False)
  
  parser.add_argument('--max_tokens',
                      type=int,
                      help='max tokens generated (for locally run models)')
  parser.add_argument('--context_window',
                      type=int,
                      help='context window in tokens (for locally run models)')
  
  parser.add_argument('--api_base',
                      type=str,
                      help='change your api_base to any OpenAI compatible api',
                      default="",
                      required=False)
  
  parser.add_argument('--use-azure',
                      action='store_true',
                      default=USE_AZURE,
                      help='use Azure OpenAI Services')
  
  parser.add_argument('--version',
                      action='store_true',
                      help='display current Emplode version')

  args = parser.parse_args()


  if args.version:
    print("Emplode", pkg_resources.get_distribution("emplode").version)
    return

  if args.max_tokens:
    emplode.max_tokens = args.max_tokens
  if args.context_window:
    emplode.context_window = args.context_window

  if args.yes:
    emplode.auto_run = True
  if args.fast:
    emplode.model = "gpt-4o-mini"
  if args.local and not args.falcon:
    
    rprint('', Markdown("**Emplode** will use `Code Llama` for local execution."), '')
        
    models = {
        '7B': 'TheBloke/CodeLlama-7B-Instruct-GGUF',
        '13B': 'TheBloke/CodeLlama-13B-Instruct-GGUF',
        '34B': 'TheBloke/CodeLlama-34B-Instruct-GGUF'
    }
    
    parameter_choices = list(models.keys())
    questions = [inquirer.List('param', message="Parameter count (smaller is faster, larger is more capable)", choices=parameter_choices)]
    answers = inquirer.prompt(questions)
    chosen_param = answers['param']

    emplode.model = models[chosen_param]
    emplode.local = True

  
  if args.debug:
    emplode.debug_mode = True
  if args.use_azure:
    emplode.use_azure = True
    emplode.local = False


  if args.model != "":
    emplode.model = args.model

    if "/" in emplode.model:
      emplode.local = True

  if args.api_base:
    emplode.api_base = args.api_base

  if args.falcon or args.model == "tiiuae/falcon-180B":
    
    rprint('', Markdown("**Emplode** will use `Falcon` for local execution."), '')
        
    models = {
        '7B': 'TheBloke/CodeLlama-7B-Instruct-GGUF',
        '40B': 'YokaiKoibito/falcon-40b-GGUF',
        '180B': 'TheBloke/Falcon-180B-Chat-GGUF'
    }
    
    parameter_choices = list(models.keys())
    questions = [inquirer.List('param', message="Parameter count (smaller is faster, larger is more capable)", choices=parameter_choices)]
    answers = inquirer.prompt(questions)
    chosen_param = answers['param']

    if chosen_param == "180B":
      rprint(Markdown("> **WARNING:** To run `Falcon-180B` we recommend at least `100GB` of RAM."))

    emplode.model = models[chosen_param]
    emplode.local = True


  emplode.chat()

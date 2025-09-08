import argparse
import os
from dotenv import load_dotenv
import requests
from packaging import version
import pkg_resources
from rich import print as rprint
from rich.markdown import Markdown

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
  DEBUG = os.getenv('EMPLODE_CLI_DEBUG', 'False') == 'True'

  parser = argparse.ArgumentParser(description='Command Emplode.')
  
  parser.add_argument('-y',
                      '--yes',
                      action='store_true',
                      default=AUTO_RUN,
                      help='execute code without user confirmation')
  parser.add_argument('-d',
                      '--debug',
                      action='store_true',
                      default=DEBUG,
                      help='prints extra information')
  
  parser.add_argument('--version',
                      action='store_true',
                      help='display current Emplode version')

  args = parser.parse_args()

  if args.version:
    print("Emplode", pkg_resources.get_distribution("emplode").version)
    return

  if args.yes:
    emplode.auto_run = True

  if args.debug:
    emplode.debug_mode = True

  emplode.chat()

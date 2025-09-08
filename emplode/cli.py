import argparse
from dotenv import load_dotenv

load_dotenv()

def cli(emplode):
  parser = argparse.ArgumentParser(description='Command Emplode.')
  parser.add_argument('-y',
                      '--yes',
                      action='store_true',
                      default=False,
                      help='execute code without user confirmation')
  args = parser.parse_args()

  if args.yes:
    emplode.auto_run = True

  emplode.chat()

def cli_entry():
  from .emplode import Emplode
  cli(Emplode())

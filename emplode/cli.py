import argparse

def cli(emplode):
  parser = argparse.ArgumentParser(description='Emplode')
  parser.add_argument('-y', '--yes', action='store_true', help='execute code without confirmation')
  args = parser.parse_args()

  if args.yes:
    emplode.auto_run = True

  emplode.chat()

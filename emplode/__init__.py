from .emplode import Emplode

_instance = Emplode()

def chat(message=None, return_messages=False):
  return _instance.chat(message=message, return_messages=return_messages)

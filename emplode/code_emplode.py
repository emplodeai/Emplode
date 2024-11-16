import subprocess
import webbrowser
import tempfile
import threading
import traceback
import platform
import time
import ast
import sys
import os
import re


def run_html(html_content):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".html") as f:
        f.write(html_content.encode())

    webbrowser.open('file://' + os.path.realpath(f.name))

    return f"Saved to {os.path.realpath(f.name)} and opened with the user's default web browser."

language_map = {
  "python": {
    "start_cmd": sys.executable + " -i -q -u",
    "print_cmd": 'print("{}")'
  },
  "R": {
    "start_cmd": "R -q --vanilla",
    "print_cmd": 'print("{}")'
  },
  "shell": {
    "start_cmd": 'cmd.exe' if platform.system() == 'Windows' else os.environ.get('SHELL', 'bash'),
    "print_cmd": 'echo "{}"'
  },
  "javascript": {
    "start_cmd": "node -i",
    "print_cmd": 'console.log("{}")'
  },
  "applescript": {
    "start_cmd": os.environ.get('SHELL', '/bin/zsh'),
    "print_cmd": 'log "{}"'
  },
  "html": {
    "open_subprocess": False,
    "run_function": run_html,
  }
}

class CodeEmplode:

  def __init__(self, language, debug_mode):
    self.language = language
    self.proc = None
    self.active_line = None
    self.debug_mode = debug_mode

  def start_process(self):
    start_cmd = language_map[self.language]["start_cmd"]

    self.proc = subprocess.Popen(start_cmd.split(),
                                 stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 text=True,
                                 bufsize=0)

    threading.Thread(target=self.save_and_display_stream,
                     args=(self.proc.stdout, False), 
                     daemon=True).start()
    threading.Thread(target=self.save_and_display_stream,
                     args=(self.proc.stderr, True), 
                     daemon=True).start()

  def update_active_block(self):
      
      self.output = truncate_output(self.output)

      self.active_block.active_line = self.active_line
      self.active_block.output = self.output
      self.active_block.refresh()

  def run(self):

    self.code = self.active_block.code

    open_subprocess = language_map[self.language].get("open_subprocess", True)
    if not self.proc and open_subprocess:
      try:
        self.start_process()
      except:
  
        traceback_string = traceback.format_exc()
        self.output = traceback_string
        self.update_active_block()

        time.sleep(0.1)

        return self.output

    self.output = ""

    self.print_cmd = language_map[self.language].get("print_cmd")
    code = self.code

    if self.print_cmd:
      try:
        code = self.add_active_line_prints(code)
      except:

        traceback_string = traceback.format_exc()
        self.output = traceback_string
        self.update_active_block()

        time.sleep(0.1)

        return self.output

    if self.language == "python":
      code = wrap_in_try_except(code)

    code_lines = code.split("\n")
    code_lines = [c for c in code_lines if c.strip() != ""]
    code = "\n".join(code_lines)

    if self.print_cmd and self.language != "applescript":
      code += "\n\n" + self.print_cmd.format('END_OF_EXECUTION')

    if self.language == "applescript":
      code = code.replace('"', r'\"')
      code = '"' + code + '"'
      code = "osascript -e " + code
      code += '\necho "END_OF_EXECUTION"'

    if self.debug_mode:
      print("Running code:")
      print(code)
      print("---")

    if self.language == "html":
      output = language_map["html"]["run_function"](code)
      return output

    self.done = threading.Event()
    self.done.clear()

    try:
      self.proc.stdin.write(code + "\n")
      self.proc.stdin.flush()
    except BrokenPipeError:
      self.start_process()
      self.run()
      return

    self.done.wait()

    time.sleep(0.1)

    return self.output

  def add_active_line_prints(self, code):
    if platform.system() == 'Windows':
       return code
  
    if self.language == 'R':
       return code

    if self.language == "python":
      return add_active_line_prints_to_python(code)

    code_lines = code.strip().split('\n')

    if self.language == "shell":
      if len(code_lines) > 1:
        return code
      if "for" in code or "do" in code or "done" in code:
        return code
      for line in code_lines:
        if line.startswith(" "):
          return code

    modified_code_lines = []

    for i, line in enumerate(code_lines):
      leading_whitespace = ""

      for next_line in code_lines[i:]:
        if next_line.strip():
          leading_whitespace = next_line[:len(next_line) -
                                         len(next_line.lstrip())]
          break

      print_line = self.print_cmd.format(f"ACTIVE_LINE:{i+1}")
      print_line = leading_whitespace + print_line

      modified_code_lines.append(print_line)
      modified_code_lines.append(line)

    code = "\n".join(modified_code_lines)
    return code

  def save_and_display_stream(self, stream, is_error_stream):
    for line in iter(stream.readline, ''):

      if self.debug_mode:
        print("Recieved output line:")
        print(line)
        print("---")

      line = line.strip()

      if self.language == "javascript":
        if "Welcome to Node.js" in line:
          continue
        if line in ["undefined", 'Type ".help" for more information.']:
          continue
        line = re.sub(r'^\s*(>\s*)+', '', line)

      if self.language == "python":
        if re.match(r'^(\s*>>>\s*|\s*\.\.\.\s*)', line):
          continue

      if self.language == "R":
        if re.match(r'^(\s*>>>\s*|\s*\.\.\.\s*)', line):
          continue

      if line.startswith("ACTIVE_LINE:"):
        self.active_line = int(line.split(":")[1])
      elif "END_OF_EXECUTION" in line:
        self.done.set()
        self.active_line = None
      elif self.language == "R" and "Execution halted" in line:
        self.done.set()
        self.active_line = None
      elif is_error_stream and "KeyboardInterrupt" in line:
        raise KeyboardInterrupt
      else:
        self.output += "\n" + line
        self.output = self.output.strip()

      self.update_active_block()

def truncate_output(data):
  needs_truncation = False

  max_output_chars = 2000

  message = f'Output truncated. Showing the last {max_output_chars} characters.\n\n'

  if data.startswith(message):
    data = data[len(message):]
    needs_truncation = True

  if len(data) > max_output_chars or needs_truncation:
    data = message + data[-max_output_chars:]

  return data

class AddLinePrints(ast.NodeTransformer):

    def insert_print_statement(self, line_number):
        return ast.Expr(
            value=ast.Call(
                func=ast.Name(id='print', ctx=ast.Load()),
                args=[ast.Constant(value=f"ACTIVE_LINE:{line_number}")],
                keywords=[]
            )
        )

    def process_body(self, body):
        new_body = []

        if not isinstance(body, list):
            body = [body]

        for sub_node in body:
            if hasattr(sub_node, 'lineno'):
                new_body.append(self.insert_print_statement(sub_node.lineno))
            new_body.append(sub_node)

        return new_body

    def visit(self, node):
        new_node = super().visit(node)

        if hasattr(new_node, 'body'):
            new_node.body = self.process_body(new_node.body)

        if hasattr(new_node, 'orelse') and new_node.orelse:
            new_node.orelse = self.process_body(new_node.orelse)

        if isinstance(new_node, ast.Try):
            for handler in new_node.handlers:
                handler.body = self.process_body(handler.body)
            if new_node.finalbody:
                new_node.finalbody = self.process_body(new_node.finalbody)

        return new_node

def add_active_line_prints_to_python(code):
    tree = ast.parse(code)
    transformer = AddLinePrints()
    new_tree = transformer.visit(tree)
    return ast.unparse(new_tree)

def wrap_in_try_except(code):
    code = "import traceback\n" + code

    parsed_code = ast.parse(code)

    try_except = ast.Try(
        body=parsed_code.body,
        handlers=[
            ast.ExceptHandler(
                type=ast.Name(id="Exception", ctx=ast.Load()),
                name=None,
                body=[
                    ast.Expr(
                        value=ast.Call(
                            func=ast.Attribute(value=ast.Name(id="traceback", ctx=ast.Load()), attr="print_exc", ctx=ast.Load()),
                            args=[],
                            keywords=[]
                        )
                    ),
                ]
            )
        ],
        orelse=[],
        finalbody=[]
    )

    parsed_code.body = [try_except]

    return ast.unparse(parsed_code)

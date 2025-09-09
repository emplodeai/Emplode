<h1 align="center">Emplode</h1>

Simple terminal agent that executes code on your machine.

## Quick Start

```shell
pip install emplode
emplode
```

## Python

```python
import emplode
emplode.chat("Organize my downloads by year.")
emplode.chat()
```

## CLI

Only one flag is supported:

- `-y` / `--yes`: run code without asking for confirmation.

## How it works

Emplode uses a function-calling model (gpt-5) with a single function `run_code(language, code)`. When the model calls the function, the code is executed locally and the output is returned to the model.

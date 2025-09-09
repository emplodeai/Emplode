# Emplode

Agent that performs actions on your system by executing code.

Emplode uses a single model: GPT-5 via OpenAI. Set OPENAI_API_KEY and start the CLI to chat and let Emplode run code locally using the built-in `run_code` tool.

## Quick Start

```shell
pip install emplode
export OPENAI_API_KEY=YOUR_KEY # or set in a .env file
emplode
```

You should see:

```
> Model set to `GPT-5`
```

- Use `-y` to auto-run code without confirmation: `emplode -y`
- Or run programmatically:

```python
import emplode
emplode.chat("Organize all images in my downloads folder into subfolders by year, naming each folder after the year.")
emplode.chat()  # interactive
```

## Requirements

- OPENAI_API_KEY must be set. Only OpenAI’s API is supported.
- Emplode uses OpenAI SDK v1 with Chat Completions, streaming, and a single function tool `run_code`.

## Notes

- Local/HuggingFace models, Azure, and custom API base options have been removed.
- CLI flags have been simplified; only `-y/--yes` is supported.

<h1 align="center">Emplode</h1>

<p align="center">
    <a href="https://discord.gg/6p3fD6rBVm">
        <img alt="Discord" src="https://img.shields.io/discord/1146610656779440188?logo=discord&style=flat&logoColor=white"/>
    </a>
    <img src="https://img.shields.io/static/v1?label=license&message=MIT&color=white&style=flat" alt="License"/>
    <br><br>
    <b>Let language models run code on your computer.</b>
</p>

<br>

**Emplode** lets LLMs run code locally. You can chat with Emplode in your terminal by running `emplode` after installing.

This provides a natural-language interface to your computer's general-purpose capabilities:

- Create, edit and arrange files.
- Control a browser to perform research
- Plot, clean, and analyze large datasets
- ...etc.

<br>

## Quick Start

```shell
pip install emplode
```

### Terminal

After installation, simply run `emplode`:

```shell
emplode
```

### Python

```python
import emplode

emplode.chat("Plot AAPL and META's normalized stock prices") # Executes a single command
emplode.chat() # Starts an interactive chat
```

## Commands

### Change the Model

For `gpt-4o-mini`, use fast mode:

```shell
emplode --fast
```

In Python, you will need to set the model manually:

```python
emplode.model = "gpt-4o-mini"
```

### Running Emplode locally

You can run `emplode` in local mode from the command line to use `Code Llama`:

```shell
emplode --local
```

Or run any Hugging Face model **locally** by using its repo ID (e.g. "tiiuae/falcon-180B"):

```shell
emplode --model tiiuae/falcon-180B
```


### Configuration with .env

Emplode allows you to set default behaviors using a .env file. This provides a flexible way to configure it without changing command-line arguments every time.

Here's a sample .env configuration:

```
EMPLODE_CLI_AUTO_RUN=False
EMPLODE_CLI_FAST_MODE=False
EMPLODE_CLI_LOCAL_RUN=False
EMPLODE_CLI_DEBUG=False
```

You can modify these values in the .env file to change the default behavior of the Emplode

## How Does it Work?

Emplode equips a [function-calling model](https://platform.openai.com/docs/guides/gpt/function-calling) with an `exec()` function, which accepts a `language` (like "Python" or "JavaScript") and `code` to run.

<br>

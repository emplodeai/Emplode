<h1 align="center">/Emplode.</h1>

<p align="center">
    <a href="https://discord.gg/uZmvdFpSyW">
        <img alt="Discord" src="https://img.shields.io/discord/1172527582684651600?logo=discord&style=flat&logoColor=white"/>
    </a>
    <br><br>
    <b>Agent that performs action on your system by executing code.</b>
</p>

<br>

**Emplode** performs actions on your system by executing code locally. You can chat with Emplode in your terminal by running `emplode` after installing.

This provides a natural-language interface to your system's general-purpose capabilities:

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

emplode.chat("Organize all images in my downloads folder into subfolders by year, naming each folder after the year.") # Executes a single command
emplode.chat() # Starts an interactive chat
```

## Commands

Emplode now uses a single model, `gpt-5`, everywhere. There is no model selection and no local model support.

- `-y`, `--yes`: execute code without user confirmation
- `-d`, `--debug`: prints extra information
- `--version`: display current Emplode version

### Configuration with .env

Emplode allows you to set default behaviors using a .env file. This provides a flexible way to configure it without changing command-line arguments every time.

Here's a sample .env configuration:

```
EMPLODE_CLI_AUTO_RUN=False
EMPLODE_CLI_DEBUG=False
```

You can modify these values in the .env file to change the default behavior of Emplode.

## How Does it Work?

Emplode equips a function-calling model with an `exec()` function, which accepts a `language` (like "Python" or "JavaScript") and `code` to run.

<br>

import os
import sys
import appdirs
import traceback
import inquirer
import subprocess
from rich import print
from rich.markdown import Markdown
import os
import shutil
from huggingface_hub import list_files_info, hf_hub_download


def get_hf_llm(repo_id, debug_mode, context_window):

    if "TheBloke/CodeLlama-" not in repo_id:
      print('', Markdown(f"**Emplode** will use `{repo_id}` for local execution."), '')

    raw_models = list_gguf_files(repo_id)
    
    if not raw_models:
        print(f"Failed. Are you sure there are GGUF files in `{repo_id}`?")
        return None

    combined_models = group_and_combine_splits(raw_models)

    selected_model = None

    if len(combined_models) > 3:

        choices = [
            format_quality_choice(combined_models[0], "Small"),
            format_quality_choice(combined_models[len(combined_models) // 2], "Medium"),
            format_quality_choice(combined_models[-1], "Large"),
            "See More"
        ]
        questions = [inquirer.List('selected_model', message="Quality (smaller is faster, larger is more capable)", choices=choices)]
        answers = inquirer.prompt(questions)
        if answers["selected_model"].startswith("Small"):
            selected_model = combined_models[0]["filename"]
        elif answers["selected_model"].startswith("Medium"):
            selected_model = combined_models[len(combined_models) // 2]["filename"]
        elif answers["selected_model"].startswith("Large"):
            selected_model = combined_models[-1]["filename"]
    
    if selected_model == None:
      
        choices = [format_quality_choice(model) for model in combined_models]
        questions = [inquirer.List('selected_model', message="Quality (smaller is faster, larger is more capable)", choices=choices)]
        answers = inquirer.prompt(questions)
        for model in combined_models:
            if format_quality_choice(model) == answers["selected_model"]:
                selected_model = model["filename"]
                break

    if confirm_action("Use GPU? (Large models might crash on GPU, but will run more quickly)"):
      n_gpu_layers = -1
    else:
      n_gpu_layers = 0

    user_data_dir = appdirs.user_data_dir("Emplode")
    default_path = os.path.join(user_data_dir, "models")

    os.makedirs(default_path, exist_ok=True)

    directories_to_check = [
        default_path,
        "llama.cpp/models/",
        os.path.expanduser("~") + "/llama.cpp/models/",
        "/"
    ]

    for directory in directories_to_check:
        path = os.path.join(directory, selected_model)
        if os.path.exists(path):
            model_path = path
            break
    else:
        download_path = os.path.join(default_path, selected_model)
      
        print(f"This language model was not found on your system.\n\nDownload to `{default_path}`?", "")
        if confirm_action(""):
            for model_details in combined_models:
                if model_details["filename"] == selected_model:
                    selected_model_details = model_details

                    if not enough_disk_space(selected_model_details['Size'], default_path):
                        print(f"You do not have enough disk space available to download this model.")
                        return None

            split_files = [model["filename"] for model in raw_models if selected_model in model["filename"]]
            
            if len(split_files) > 1:
                for split_file in split_files:
                    split_path = os.path.join(default_path, split_file)
                    if os.path.exists(split_path):
                        if not confirm_action(f"Split file {split_path} already exists. Download again?"):
                            continue
                    hf_hub_download(
                        repo_id=repo_id,
                        filename=split_file,
                        local_dir=default_path,
                        local_dir_use_symlinks=False,
                        resume_download=True)
        
                actually_combine_files(default_path, selected_model, split_files)
            else:
                hf_hub_download(
                    repo_id=repo_id,
                    filename=selected_model,
                    local_dir=default_path,
                    local_dir_use_symlinks=False,
                    resume_download=True)

            model_path = download_path
        
        else:
            print('\n', "Download cancelled. Exiting.", '\n')
            return None

    print(Markdown(f"Model found at `{model_path}`"))
  
    try:
        from llama_cpp import Llama
    except:
        if debug_mode:
            traceback.print_exc()
        message = "Local LLM interface package not found. Install `llama-cpp-python`?"
        if confirm_action(message):
    
            import platform
            
            def check_command(command):
                try:
                    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    return True
                except subprocess.CalledProcessError:
                    return False
                except FileNotFoundError:
                    return False
            
            def install_llama(backend):
                env_vars = {
                    "FORCE_CMAKE": "1"
                }
                
                if backend == "cuBLAS":
                    env_vars["CMAKE_ARGS"] = "-DLLAMA_CUBLAS=on"
                elif backend == "hipBLAS":
                    env_vars["CMAKE_ARGS"] = "-DLLAMA_HIPBLAS=on"
                elif backend == "Metal":
                    env_vars["CMAKE_ARGS"] = "-DLLAMA_METAL=on"
                else: 
                    env_vars["CMAKE_ARGS"] = "-DLLAMA_BLAS=ON -DLLAMA_BLAS_VENDOR=OpenBLAS"
                
                try:
                    subprocess.run([sys.executable, "-m", "pip", "install", "llama-cpp-python"], env={**os.environ, **env_vars}, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error during installation with {backend}: {e}")
            
            def supports_metal():
                if platform.system() == "Darwin":
                    mac_version = tuple(map(int, platform.mac_ver()[0].split('.')))
                    if mac_version >= (10, 11):
                        return True
                return False
        
            if check_command(["nvidia-smi"]):
                install_llama("cuBLAS")
            elif check_command(["rocminfo"]):
                install_llama("hipBLAS")
            elif supports_metal():
                install_llama("Metal")
            else:
                install_llama("OpenBLAS")
          
            from llama_cpp import Llama
            print('', Markdown("Finished downloading `Code-Llama` interface."), '')

            if platform.system() == "Darwin":
                if platform.machine() != "arm64":
                    print("Warning: You are using Apple Silicon (M1/M2) Mac but your Python is not of 'arm64' architecture.")
                    print("The llama.ccp x86 version will be 10x slower on Apple Silicon (M1/M2) Mac.")
                    print("\nTo install the correct version of Python that supports 'arm64' architecture:")
                    print("1. Download Miniforge for M1/M2:")
                    print("wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh")
                    print("2. Install it:")
                    print("bash Miniforge3-MacOSX-arm64.sh")
                    print("")
      
        else:
            print('', "Installation cancelled. Exiting.", '')
            return None
        
    assert os.path.isfile(model_path)
    llama_2 = Llama(model_path=model_path, n_gpu_layers=n_gpu_layers, verbose=debug_mode, n_ctx=context_window)
      
    return llama_2

def confirm_action(message):
    question = [
        inquirer.Confirm('confirm',
                         message=message,
                         default=True),
    ]

    answers = inquirer.prompt(question)
    return answers['confirm']


import os
import inquirer
from huggingface_hub import list_files_info, hf_hub_download, login
from typing import Dict, List, Union

def list_gguf_files(repo_id: str) -> List[Dict[str, Union[str, float]]]:
    try:
      files_info = list_files_info(repo_id=repo_id)
    except Exception as e:
      if "authentication" in str(e).lower():
        print("You likely need to be logged in to HuggingFace to access this language model.")
        print(f"Visit this URL to log in and apply for access to this language model: https://huggingface.co/{repo_id}")
        print("Then, log in here:")
        login()
        files_info = list_files_info(repo_id=repo_id)
  
    gguf_files = [file for file in files_info if "gguf" in file.rfilename]

    gguf_files = sorted(gguf_files, key=lambda x: x.size)

    result = []
    for file in gguf_files:
        size_in_gb = file.size / (1024**3)
        filename = file.rfilename
        result.append({
            "filename": filename,
            "Size": size_in_gb,
            "RAM": size_in_gb + 2.5,
        })

    return result

from typing import List, Dict, Union

def group_and_combine_splits(models: List[Dict[str, Union[str, float]]]) -> List[Dict[str, Union[str, float]]]:
    grouped_files = {}

    for model in models:
        base_name = model["filename"].split('-split-')[0]
        
        if base_name in grouped_files:
            grouped_files[base_name]["Size"] += model["Size"]
            grouped_files[base_name]["RAM"] += model["RAM"]
            grouped_files[base_name]["SPLITS"].append(model["filename"])
        else:
            grouped_files[base_name] = {
                "filename": base_name,
                "Size": model["Size"],
                "RAM": model["RAM"],
                "SPLITS": [model["filename"]]
            }

    return list(grouped_files.values())


def actually_combine_files(default_path: str, base_name: str, files: List[str]) -> None:
    files.sort()    
    base_path = os.path.join(default_path, base_name)
    with open(base_path, 'wb') as outfile:
        for file in files:
            file_path = os.path.join(default_path, file)
            with open(file_path, 'rb') as infile:
                outfile.write(infile.read())
            os.remove(file_path)

def format_quality_choice(model, name_override = None) -> str:
    if name_override:
        name = name_override
    else:
        name = model['filename']
    return f"{name} | Size: {model['Size']:.1f} GB, Estimated RAM usage: {model['RAM']:.1f} GB"

def enough_disk_space(size, path) -> bool:
    _, _, free = shutil.disk_usage(path)

    free_gb = free / (2**30) 

    if free_gb > size:
        return True

    return False

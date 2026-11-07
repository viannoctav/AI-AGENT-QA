import json
import os

def get_folder(folder_name):

    with open("configs/files.json","r") as f:
        config = json.load(f)

    return config[folder_name]["path"]


def list_files(folder_name):

    folder = get_folder(folder_name)

    return os.listdir(folder)
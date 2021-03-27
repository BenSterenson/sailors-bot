from typing import Dict

import yaml


def _load_file() -> Dict:
    with open("settings.yaml") as yaml_file:
        configuration = yaml.safe_load(yaml_file)
    return configuration


config = _load_file()

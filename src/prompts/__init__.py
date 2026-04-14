import os, glob

PROMPT_DIR = os.path.dirname(__file__)

all_prompts = {}
for filepath in glob.glob(os.path.join(PROMPT_DIR, "*.txt")):
    with open(filepath, 'r') as file:
        prompt_name = os.path.basename(filepath).replace('.txt', '').upper()
        all_prompts[prompt_name.upper()] = file.read().strip()
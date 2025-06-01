from github import Github
import os

from config import GITHUB_TOKEN, GITHUB_REPO

def push_to_github(local_file):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(GITHUB_REPO)
    with open(local_file, "r", encoding="utf-8") as f:
        content = f.read()
    try:
        contents = repo.get_contents(local_file)
        repo.update_file(contents.path, f"maj {local_file}", content, contents.sha)
    except Exception:
        repo.create_file(local_file, f"création {local_file}", content)

def ensure_file_and_push(filename, header):
    if not os.path.isfile(filename):
        with open(filename, "w", encoding="utf-8") as f:
            f.write(header + "\n")
        push_to_github(filename)

import os
import shutil
import subprocess

demo_dir = os.path.abspath("demo_git_repo")
if os.path.exists(demo_dir):
    shutil.rmtree(demo_dir)
os.makedirs(demo_dir, exist_ok=True)

def git(args, author=None, email=None):
    if author:
        subprocess.run(["git", "-C", demo_dir, "config", "user.name", author], check=True)
    if email:
        subprocess.run(["git", "-C", demo_dir, "config", "user.email", email], check=True)
    subprocess.run(["git", "-C", demo_dir] + args, check=True)

git(["init"])
git(["config", "user.name", "Sarah Connor"], "Sarah Connor", "sarah@resistance.org")

# Commit 1 by Sarah
with open(os.path.join(demo_dir, "main.py"), "w", encoding="utf-8") as f:
    f.write("import os\nimport sys\n\ndef main():\n    print('Starting system...')\n    return 0\n")
git(["add", "main.py"])
git(["commit", "-m", "Initial project scaffold and main entry"])

# Commit 2 by John
with open(os.path.join(demo_dir, "models.py"), "w", encoding="utf-8") as f:
    f.write("class SecurityModel:\n    def __init__(self, key):\n        self.key = key\n\n    def verify(self):\n        return True\n")
git(["add", "models.py"], "John Connor", "john@resistance.org")
git(["commit", "-m", "Add SecurityModel class"])

# Commit 3 by Kyle
with open(os.path.join(demo_dir, "config.py"), "w", encoding="utf-8") as f:
    f.write("PORT = 8080\nDEBUG = True\nTIMEOUT = 30\n")
with open(os.path.join(demo_dir, "main.py"), "w", encoding="utf-8") as f:
    f.write("import os\nimport sys\nimport config\nfrom models import SecurityModel\n\ndef main():\n    print('Starting node on port', config.PORT)\n    model = SecurityModel('secret')\n    assert model.verify()\n    return 0\n\nif __name__ == '__main__':\n    main()\n")
git(["add", "."], "Kyle Reese", "kyle@resistance.org")
git(["commit", "-m", "Integrate security model and configuration"])

# Commit 4 by Sarah
with open(os.path.join(demo_dir, "README.md"), "w", encoding="utf-8") as f:
    f.write("# Resistance Secure Node\n\nA local secure node analyzer.\n\n## Installation\n`pip install -r requirements.txt`\n")
with open(os.path.join(demo_dir, "test_models.py"), "w", encoding="utf-8") as f:
    f.write("from models import SecurityModel\n\ndef test_security():\n    m = SecurityModel('abc')\n    assert m.verify() is True\n")
# Add a lockfile to test smart filter exclusion
with open(os.path.join(demo_dir, "package-lock.json"), "w", encoding="utf-8") as f:
    f.write('{\n  "name": "resistance-node",\n  "version": "1.0.0",\n  "lockfileVersion": 3\n}\n')
git(["add", "."], "Sarah Connor", "sarah@resistance.org")
git(["commit", "-m", "Add README, unit tests, and package-lock.json"])

print("Demo repository successfully created at:", demo_dir)

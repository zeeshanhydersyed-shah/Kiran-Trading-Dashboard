"""
Run this once from C:\Users\Lenovo\psx_pipeline:
    python fix_large_files.py
"""
import subprocess, sys, os

repo = os.path.dirname(os.path.abspath(__file__))
os.chdir(repo)

def run(cmd, **kw):
    print(f"\n>>> {cmd}")
    r = subprocess.run(cmd, shell=True, **kw)
    if r.returncode != 0:
        print(f"FAILED (exit {r.returncode})")
        sys.exit(1)

# 1. Remove lock file if present
lock = os.path.join(repo, ".git", "HEAD.lock")
if os.path.exists(lock):
    os.remove(lock)
    print("Removed HEAD.lock")

# 2. Stash everything
run("git stash")

# 3. Scrub large files from history
os.environ["FILTER_BRANCH_SQUELCH_WARNING"] = "1"
run('git filter-branch --force --index-filter "git rm --cached --ignore-unmatch features_dataset.csv support_signals_20260521_130920.csv" --prune-empty -- --all')

# 4. Pop stash
run("git stash pop")

# 5. Add to .gitignore
gitignore = os.path.join(repo, ".gitignore")
with open(gitignore, "a") as f:
    f.write("\nfeatures_dataset.csv\nsupport_signals_20260521_130920.csv\n")
print("Updated .gitignore")

# 6. Commit and push
run("git add .gitignore dashboard.py")
run('git commit -m "fix: remove large files, decimal formatting, retrain guard"')
run("git push origin main --force")

print("\n✅ Done! Streamlit Cloud will redeploy in ~60 seconds.")

"""Runs build_harbour.py several times, one after another, with the settings in runs.json (for trying looks)"""
import json
import os
import subprocess

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "..", "..", "port", "build_harbour.py")
runs = json.load(open(os.path.join(HERE, "runs.json")))
with open(os.path.join(HERE, "runner.log"), "w") as log:
    for run in runs:
        env = dict(os.environ, **run)
        log.write(f"RUN {run}\n")
        log.flush()
        subprocess.run([bpy.app.binary_path, "--background", "--python", SCRIPT], stdout=log, stderr=subprocess.STDOUT,
                       env=env, creationflags=0x08000000)
    log.write("ALL RUNS DONE\n")

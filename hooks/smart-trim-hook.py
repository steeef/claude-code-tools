#!/usr/bin/env python3
import json
import sys
import subprocess

data = json.load(sys.stdin)
session_id = data.get('session_id', '')
prompt = data.get('prompt', '')

if '/smart-trim' in prompt:
    subprocess.run(['smart-trim', session_id])

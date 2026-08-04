"""One-time (or re-auth) Google sign-in for Jarvis.

Run this any time you need to (re)connect your Google account, INCLUDING after the
requested permissions change (e.g. when Gmail send was added):
    .venv\\Scripts\\python.exe connect_google.py

A browser window opens; sign in and grant access. A token.json is saved so Jarvis
can read your Calendar/Gmail and compose+send email silently afterwards. On the
consent screen, make sure the "Send email on your behalf" box stays checked.
"""
import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
import google_integration as g

print("Opening your browser to connect Google (Calendar read + Gmail read/compose/send)...")
print("If you see an 'unverified app' warning, click Advanced -> Go to Jarvis (unsafe).")
print("On the permissions screen, leave the Gmail 'send email' box checked.")
g.authorize_interactive()
print("Connected! token.json saved with send permission. You can close this window.")

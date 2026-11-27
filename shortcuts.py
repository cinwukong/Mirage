"""
Your own shortcuts: "when I say <phrase>, do <action> with <target>".

Used by the "+ New shortcut" dialog (to check and save one) and by the engine (to find the one you said).
A shortcut is a dict: {"phrase": "good morning", "action": "open", "target": "spotify:"}.
"""

import re

ACTIONS = ("open", "say", "type", "keys", "run")

# Your shortcuts run before anything else, so these must stay free: Mirage needs them to stop, cancel and end a chat.
RESERVED = re.compile(r"never ?mind|cancel|nothing|stop(?: it| talking| that)?|be quiet|quiet|shut up|enough|silence|"
                      r"hush|that'?s (?:all|it|everything)|thanks|thank you|no|yes|okay|ok")

KEY = re.compile(r"[a-z0-9]+")  # one key name, like ctrl, shift, s, f5, enter, volumeup


def check(cmd):
    """What's wrong with a shortcut before it's saved, in a sentence for the dialog, or None when it's fine."""
    p = phrase(cmd.get("phrase"))
    action = cmd.get("action")
    target = str(cmd.get("target") or "").strip()
    if not p:
        return "Say or type the phrase first."
    if RESERVED.fullmatch(p):
        return f"“{p}” is one Mirage needs for itself. Pick another phrase."
    if action not in ACTIONS:
        return "Pick what the shortcut should do."
    if not target:
        return {"open": "Add the website, app or file to open.", "say": "Add what Mirage should say.",
                "type": "Add the text to type.", "keys": "Add the keys to press.", "run": "Add the command to run."}[action]
    if action == "keys" and not all(KEY.fullmatch(k) for k in target.lower().replace(" ", "").split("+")):
        return "Write keys like ctrl+shift+s: key names joined by +."
    return None


def phrase(text, wake_words=("mirage",)):
    """A phrase the way Mirage compares it: lower case, no punctuation (apostrophes stay), single spaces,
    and without a wake word in front ("Mirage, good morning!" -> "good morning")."""
    t = re.sub(r"[^\w\s']", " ", str(text or "").lower())
    t = " ".join(t.split())
    for w in wake_words:
        w = " ".join(str(w).lower().split())
        if w and (t == w or t.startswith(w + " ")):
            t = t[len(w):].strip()
            break
    return t


def put(cmds, cmd):
    """Your list with this shortcut saved: a shortcut with the same phrase is replaced where it was.
    Returns (new list, replaced). The list you pass in isn't changed."""
    new = {"phrase": phrase(cmd.get("phrase")), "action": cmd.get("action"),
           "target": str(cmd.get("target") or "").strip()}
    out, replaced = [], False
    for c in cmds or []:
        if phrase(c.get("phrase")) == new["phrase"]:
            if not replaced:
                out.append(new)
                replaced = True
        else:
            out.append(dict(c))
    if not replaced:
        out.append(new)
    return out, replaced


def find(cmds, heard):
    """The shortcut whose whole phrase is what you said, or None."""
    said = phrase(heard)
    if not said:
        return None
    for c in cmds or []:
        if phrase(c.get("phrase")) == said:
            return c
    return None


def without(cmds, said):
    """Your list without the shortcut whose phrase this is (an empty phrase leaves everything)."""
    p = phrase(said)
    return [dict(c) for c in cmds or [] if not p or phrase(c.get("phrase")) != p]

RULES = {'secret': 1, 'nice': -1, 'credential': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

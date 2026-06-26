RULES = {'urgent': 1, 'whenever': -1, 'blocked': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

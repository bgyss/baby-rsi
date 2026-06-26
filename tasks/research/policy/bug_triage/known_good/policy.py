RULES = {'crash': 1, 'typo': -1, 'data loss': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

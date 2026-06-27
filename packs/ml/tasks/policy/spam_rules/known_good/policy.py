RULES = {'buy now': -1, 'meeting': 1, 'free money': -1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

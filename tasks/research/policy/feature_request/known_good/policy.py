RULES = {'please add': 1, 'works fine': -1, 'missing': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

RULES = {'not good': -1, 'not bad': 1, 'great': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

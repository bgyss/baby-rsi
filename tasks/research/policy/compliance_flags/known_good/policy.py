RULES = {'personal data': 1, 'public info': -1, 'ssn': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

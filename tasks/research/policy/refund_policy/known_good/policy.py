RULES = {'refund': 1, 'hello': -1, 'chargeback': 1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

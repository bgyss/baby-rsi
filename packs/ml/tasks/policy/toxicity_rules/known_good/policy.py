RULES = {'idiot': -1, 'thanks': 1, 'hate': -1}

def decide(text):
    lowered = text.lower()
    for phrase, label in RULES.items():
        if phrase in lowered:
            return label
    return -1

def valid(text):
    return bool(text) and text == text.lower() and all(ch.isalnum() or ch == "-" for ch in text) and "--" not in text

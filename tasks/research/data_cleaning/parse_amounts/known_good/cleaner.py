def clean(value):
    return float(value.replace("$", "").replace(",", "").strip())

class IllegalAction(Exception):
    """An action that does not fit the career's current state. The API answers it with 409."""

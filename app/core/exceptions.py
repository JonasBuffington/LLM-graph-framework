# app/core/exceptions.py
class NodeNotFoundException(Exception):
    """Raised when a node is not found for a given ID."""
    def __init__(self, message="Node not found."):
        self.message = message
        super().__init__(self.message)
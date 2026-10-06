import json
import re

# блок ```json … ``` где угодно в ответе; закрывающие кавычки могут стоять сразу после «}»
_FENCED = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ReceiptParser:
    """Parser for the LLM's response."""

    def parse(self, response: str) -> dict:
        """Parse the LLM's response and return a JSON object.

        Models wrap JSON differently: a bare object, a ```json fenced block (with or without
        a newline before the closing fence) or a block preceded by a sentence like
        "Here is the JSON:". Slicing fixed offsets broke on the latter two.
        """
        text = (response or "").strip()
        candidates = [m.group(1) for m in _FENCED.finditer(text)] + [text]
        start, end = text.find("{"), text.rfind("}")
        if 0 <= start < end:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        # Handle the case where the response is not valid JSON
        return {"error": "The LLM's response was not valid JSON."}

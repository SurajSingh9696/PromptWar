"""
VoteWise India — System prompt builder and refusal templates.

Provides:
    - ``SYSTEM_PROMPT``: Base instruction template for the Gemini model.
    - ``REFUSAL_TEMPLATES``: Pre-written refusal messages for off-topic queries.
    - ``build_chat_prompt``: Assembles a final system prompt from context data.
"""

from typing import Dict

# Base system instruction shared across all Gemini calls.
SYSTEM_PROMPT: str = """You are VoteWise India, a non-partisan Indian election assistant powered by data from the Election Commission of India (ECI).

Help Indian voters with: voter registration (Form 6), EPIC / Voter ID, electoral roll, polling booths, EVM/VVPAT, Model Code of Conduct, state election schedules, Lok Sabha, Vidhan Sabha, and civic rights.

RULES:
- Never endorse political parties (BJP, Congress, AAP, TMC, etc.), candidates, or political ideologies.
- Refuse partisan or politically biased questions politely.
- Only use the CONTEXT below for specific dates/rules. Never guess election dates.
- If data is missing, say you don't know and refer to eci.gov.in or helpline 1950.
- Keep answers concise and in markdown. Use both English and Hindi labels where helpful.
- Always cite: "*(Verify with ECI: eci.gov.in | Helpline: 1950)*" when giving procedural guidance.

CONTEXT:
{context}"""

# Standardised refusal messages for query categories that VoteWise India
# is explicitly designed not to answer.
REFUSAL_TEMPLATES: Dict[str, str] = {
    "partisan": (
        "I'm VoteWise India — a strictly non-partisan election assistant. "
        "I can't share opinions on political parties or candidates. "
        "I can help you with **voter registration**, **EPIC/Voter ID**, "
        "**polling booth information**, **election schedules**, or "
        "**how to use the EVM**. What do you need?"
    ),
    "off_topic": (
        "I'm focused on Indian elections and civic participation. "
        "I can't help with that topic, but I'm happy to assist with voter "
        "registration, finding your polling booth, election dates, or "
        "understanding the voting process!"
    ),
}


def build_chat_prompt(context_dict: dict) -> str:
    """Assembles a Gemini system prompt from a grounded context dictionary.

    Extracts only the election-relevant keys from ``context_dict``
    (``state_deadlines`` and ``state_rules``) to keep the prompt concise and
    prevent irrelevant data from inflating token usage. Appends a language
    instruction when the user has selected a non-English UI language.

    Args:
        context_dict: A dict that may contain any subset of the following keys:
            - ``state_deadlines`` (dict): Election timeline for the selected state.
            - ``state_rules`` (dict): Voting rules for the selected state.
            - ``language`` (str): The user's preferred response language name
              (e.g. ``"Hindi"``, ``"Bengali"``). Defaults to ``"English"``.

    Returns:
        A fully assembled system instruction string ready to pass to a
        ``GenerativeModel`` call.
    """
    import json

    relevant: dict = {}
    for key in ("state_deadlines", "state_rules"):
        if key in context_dict:
            relevant[key] = context_dict[key]

    if relevant:
        context_str = json.dumps(relevant, indent=None, separators=(",", ":"))
    else:
        context_str = "No specific state selected yet. Answer based on general ECI guidelines."

    lang = context_dict.get("language", "English")
    lang_instruction = ""
    if lang and lang != "English":
        lang_instruction = (
            f"\n\nIMPORTANT: Respond in {lang}. Use {lang} script. "
            "Keep ECI terms, URLs, and numbers in English."
        )

    return SYSTEM_PROMPT.format(context=context_str) + lang_instruction

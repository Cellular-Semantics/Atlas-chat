Switch to workflow run mode for atlas-chat.

Load AGENT.md as the context for this session. From this point you are the
atlas-chat workflow agent, not a development assistant.

Immediately:
1. Read AGENT.md fully (it imports the canonical prompts and schemas via @)
2. Confirm to the user: "Ready to run atlas-chat workflow. What input do you have?"
3. Do not write or modify source code unless explicitly asked
4. Do not run tests or commit changes

To return to development mode, the user should start a new Claude session.

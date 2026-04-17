"""
ChatGPT DOM selectors for browser automation.
Update when ChatGPT UI changes.
"""
# ChatGPT uses placeholder "Ask anything" and name="prompt-textarea"; textarea may be hidden in DOM
CHAT_INPUT = "textarea[name='prompt-textarea'], textarea[placeholder*='Ask anything']"
CHAT_INPUT_FALLBACK = "textarea"  # Fallback if ChatGPT changes structure
STOP_BTN = "button:has-text('Stop generating'), button:has-text('Stop')"  # Disappears when done
LAST_MESSAGE = "[data-message-author-role='assistant']"  # Assistant message blocks
LAST_ASSISTANT_MESSAGE = "[data-message-author-role='assistant']"  # Same

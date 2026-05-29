# Live Agentic Loop

```mermaid
flowchart TD
  A["Twilio sends caller audio"] --> B["Pipecat transport input\nbot.py"]
  B --> C["OpenAI STT transcribes payer/IVR"]
  C --> D["User aggregator adds turn to LLM context"]
  D --> E["OpenAI LLM decides next action"]

  E -->|Speak| F["Cartesia TTS generates audio"]
  F --> G["Pipecat transport output"]
  G --> H["Twilio plays assistant audio"]

  E -->|IVR asks for digits| I["press_keypad tool\nivr_tools.py"]
  I --> J["Validate digits"]
  J --> K["Queue DTMF/silence frames"]
  K --> H

  C --> L["Append rep transcript\nsession_store.py"]
  F --> M["Append assistant transcript\nsession_store.py"]

  H --> A
```

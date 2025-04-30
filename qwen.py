import ollama
from ollama import chat, ChatResponse
import os
import re

# Get Ollama URL from environment variable or default to localhost
OLLAMA_URL = os.environ.get('OLLAMA', 'http://localhost:11434')
# Configure Ollama client with the correct URL
ollama.host = OLLAMA_URL
print(f"Connecting to Ollama at: {OLLAMA_URL}")

# Create a custom model based on qwen
ollama.create(model='rdx', from_='qwen3:0.6b', system="You are an AI assistant for Redx retail solutions. And your name is REDEX")

# Example chat interaction
response: ChatResponse = chat(model='rdx', messages=[
  {
    'role': 'user',
    'content': 'Tell me your name',
  },
])

# Get the raw content
content = response.message.content

# Try different regex approaches
# 1. Extract content between think tags
think_pattern = re.compile(r'<think>(.*?)</think>', re.DOTALL)
think_blocks = think_pattern.findall(content)

# 2. Try to get content after the last </think> tag
parts = content.split('</think>')
if len(parts) > 1:
    last_part = parts[-1].strip()
else:
    print("")

# 3. Alternative regex approach
cleaned_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

print(cleaned_content if cleaned_content else "")

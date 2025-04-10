import os
import chromadb
import ollama
import logging

# Suppress ChromaDB logs
logging.getLogger('chromadb').setLevel(logging.ERROR)

def embed_text(text, model="all-minilm"):
    """Generate an embedding for the given text using Ollama."""
    response = ollama.embed(model=model, input=text)
    return response["embeddings"][0]

def build_collection(collection_name="crawled_docs"):
    """Create or retrieve a ChromaDB collection."""
    db_path = os.path.join(os.getcwd(), "chroma_db")
    client = chromadb.PersistentClient(path=db_path)
    try:
        collection = client.get_collection(name=collection_name)
        print(f"Using existing database with {collection.count()} documents...")
        return collection
    except Exception:
        collection = client.create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        print("Created new collection")
    return collection

def is_gibberish(text):
    """Check if input is likely gibberish or too short."""
    text = text.strip()
    if len(text) < 3 or text.endswith('[') or text.endswith('(') or text.endswith('{'):
        return True
    words = text.lower().split()
    unique_words = set(words)
    if len(unique_words) == 1 and len(words) > 1:
        return True
    if len(words) >= 3 and len(unique_words) < min(len(words) * 0.5, len(text) * 0.3):
        return True
    brackets = {'[': ']', '(': ')', '{': '}', '"': '"', "'": "'"}
    stack = []
    for char in text:
        if char in brackets.keys():
            stack.append(char)
        elif char in brackets.values():
            bracket_keys = list(brackets.keys())
            bracket_values = list(brackets.values())
            if not stack or brackets[bracket_keys[bracket_values.index(char)]] != stack[-1]:
                return True
            stack.pop()
    if stack:
        return True
    consonant_count = sum(1 for c in text.lower() if c in 'bcdfghjklmnpqrstvwxyz!@#$%^&*()_+{}|:"<>?')
    total_chars = len(text)
    if total_chars > 0 and consonant_count / total_chars > 0.7:
        return True
    if len(words) < 2:
        return True
    return False

def is_repetitive_input(text):
    """Check if input consists of repeated words."""
    words = text.lower().split()
    if not words:
        return False
    word_counts = {}
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1
    if len(word_counts) == 1 and len(words) > 1:
        return True
    most_common_word = max(word_counts.items(), key=lambda x: x[1])
    if most_common_word[1] / len(words) > 0.7 and len(words) > 2:
        return True
    return False


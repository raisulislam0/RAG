import os
import chromadb
import ollama
import logging

# Suppress ChromaDB logs
logging.getLogger('chromadb').setLevel(logging.ERROR)

def embed_text(text, model="all-minilm", check_stop=None):
    """Generate an embedding for the given text using Ollama.

    Args:
        text: The text to embed
        model: The model to use for embedding
        check_stop: Optional callback function that returns True if processing should stop

    Returns:
        The embedding vector or None if stopped
    """
    # Check if stop was requested before starting the embedding process
    if check_stop and check_stop():
        return None

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

def input_validation(text):
    """Check if input is likely gibberish or too short."""
    text = text.strip()

    # Check for basic issues
    if len(text) < 3 or text.endswith('[') or text.endswith('(') or text.endswith('{'):
        return True

    # Split into words and analyze
    words = text.lower().split()
    unique_words = set(words)

    # Check for single word repetition
    if len(unique_words) == 1 and len(words) > 1:
        return True

    # Check for low word diversity
    if len(words) >= 3 and len(unique_words) < min(len(words) * 0.5, len(text) * 0.3):
        return True

    # Check for unbalanced brackets
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

    # Check for high consonant ratio (gibberish often has too many consonants)
    consonant_count = sum(1 for c in text.lower() if c in 'bcdfghjklmnpqrstvwxyz!@#$%^&*()_+{}|:"<>?')
    total_chars = len(text)
    if total_chars > 0 and consonant_count / total_chars > 0.7:
        return True

    # Check for too many numbers or symbols
    symbol_count = sum(1 for c in text if not c.isalpha() and not c.isspace())
    if total_chars > 0 and symbol_count / total_chars > 0.3:
        return True

    # Check for unusually long words
    avg_word_length = sum(len(word) for word in words) / max(len(words), 1)
    if avg_word_length > 15:  # Most English words are shorter than this
        return True

    # Check for too few words
    if len(words) < 2:
        return True

    return False

def is_repetitive_input(text):
    """Check if input consists of repeated words, characters, or patterns."""
    text = text.lower().strip()

    if not text:
        return False

    # Split into words
    words = text.split()
    if not words:
        return False

    # Define unique_words set
    unique_words = set(words)


    word_counts = {}
    for word in words:
        word_counts[word] = word_counts.get(word, 0) + 1

    if len(word_counts) == 1 and len(words) > 1:
        return True


    most_common_word = max(word_counts.items(), key=lambda x: x[1])
    if most_common_word[1] / len(words) > 0.5 and len(words) > 2:
        return True


    for word in unique_words:
        if len(word) > 3:

            char_counts = {}
            for char in word:
                char_counts[char] = char_counts.get(char, 0) + 1
            most_common_char = max(char_counts.items(), key=lambda x: x[1])
            if most_common_char[1] > 3 and most_common_char[1] / len(word) > 0.5:
                return True


    if len(text) > 5:
        for pattern_length in range(1, min(5, len(text) // 2)):
            pattern = text[:pattern_length]
            # Check if the pattern repeats at least 3 times
            repetitions = 0
            for i in range(0, len(text) - pattern_length + 1, pattern_length):
                if text[i:i+pattern_length] == pattern:
                    repetitions += 1
                else:
                    break
            if repetitions >= 3:
                return True


    if len(unique_words) >= 2:
        for word1 in unique_words:
            if len(word1) <= 3:
                continue
            similar_words = 0
            for word2 in unique_words:
                if word1 != word2 and (word1 in word2 or word2 in word1):
                    similar_words += 1
            if similar_words > 0 and similar_words / len(unique_words) > 0.5:
                return True

    return False


import os
import chromadb
import ollama
import logging

# Suppress ChromaDB logs
logging.getLogger('chromadb').setLevel(logging.ERROR)

OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://app:11434')
ollama.host = OLLAMA_HOST

def embed_text(text, model="all-minilm", check_stop=None):
    """Generate an embedding for the given text using Ollama.

    Args:
        text: The text to embed
        model: The model to use for embedding
        check_stop: Optional callback function that returns True if processing should stop

    Returns:
        The embedding vector or None if stopped
    """
    if check_stop and check_stop():
        return None

    try:
        response = ollama.embed(model=model, input=text)
        return response["embeddings"][0]
    except Exception as e:
        print(f"Error embedding text: {str(e)}")
        import time
        time.sleep(2)
        try:
            response = ollama.embed(model=model, input=text)
            return response["embeddings"][0]
        except Exception as e:
            print(f"Failed to embed text after retry: {str(e)}")
            return None

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


def is_repetitive_input(text):
    """Check if input is repetitive or nonsensical."""
    if not text or len(text.strip()) < 3:
        return True
        
    # Check for repetitive patterns
    words = text.lower().split()
    if len(words) >= 3:
        if len(set(words)) <= len(words) * 0.3:
            return True
            
    return False

